from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from typing import Any, Callable

from fastapi import HTTPException

from local_asr_server.app_services import AppServices
from local_asr_server.analysis_templates import (
    DEFAULT_ANALYSIS_TYPE,
    DEFAULT_PIPELINE_ID,
    DEFAULT_TEMPLATE_VERSION,
    SHARED_NOTES_TEMPLATE_ID,
    AnalysisPipeline,
    AnalysisTemplate,
    get_pipeline,
    get_template,
    template_for_analysis_type,
)
from local_asr_server.jobs import JobStore
from local_asr_server.jobs.models import TERMINAL_JOB_STATUSES
from local_asr_server.schemas import ANALYSIS_LLM_REQUEST_FIELDS, AnalysisPipelineRequest, AnalysisRequest
from local_asr_server.services.analysis_service import AnalysisService
from local_asr_server.settings import load_settings
from local_asr_server.llm import DEFAULT_GEMINI_MODEL
from local_asr_server.runtime.models import resolve_local_llm_model_path
from local_asr_server.runtime.workload_arbiter import (
    HeavyWorkloadArbiter,
    WorkloadAdmissionRejected,
    WorkloadArbiterClosed,
    WorkloadQueueFull,
)

ANALYSIS_JOB_TYPE = "analysis"
logger = logging.getLogger("uvicorn.error")
AnalysisTerminalCallback = Callable[[dict[str, Any]], None]


class AnalysisJobManager:
    """Runs analysis workflows as persistent jobs backed by JobStore."""

    def __init__(
        self,
        services: AppServices,
        store: JobStore,
        *,
        arbiter: HeavyWorkloadArbiter | None = None,
    ) -> None:
        self._services = services
        self._store = store
        self._arbiter = arbiter

    def create(
        self,
        body: AnalysisRequest,
        *,
        on_terminal: AnalysisTerminalCallback | None = None,
    ) -> dict[str, Any]:
        body = self._with_recording_transcription(body)
        body = self._with_template_defaults(body)
        job_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        scope_type, scope_id = self._resolve_scope(body, run_id)
        settings = AnalysisService.settings_with_request_overrides(load_settings(), body)
        provider = settings.get("llm_provider", "mock")
        effective_model = self._effective_model(provider, settings)
        llm_options = self._llm_options(settings, provider=provider, model=effective_model)
        payload = self._request_payload(body)
        input_hash = self._input_hash(body, payload)

        self._store.create(
            job_id=job_id,
            job_type=ANALYSIS_JOB_TYPE,
            scope_type=scope_type,
            scope_id=scope_id,
            payload={
                **payload,
                "analysis_run_id": run_id,
                "llm_options": llm_options,
                "input_hash": input_hash,
            },
        )
        self._services.catalog.create_analysis_run(
            {
                "id": run_id,
                "job_id": job_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "transcription_id": body.transcription_id,
                "recording_id": body.recording_id,
                "analysis_type": body.analysis_type or DEFAULT_ANALYSIS_TYPE,
                "template_id": body.template_id,
                "template_version": body.template_version,
                "pipeline_run_id": body.pipeline_run_id,
                "provider": provider,
                "model": effective_model,
                "temperature": llm_options.get("temperature"),
                "reasoning": llm_options.get("reasoning") or "auto",
                "effective_reasoning": None,
                "show_thinking": llm_options.get("show_thinking", False),
                "max_output_tokens": llm_options.get("max_output_tokens"),
                "json_mode": llm_options.get("json_mode", True),
                "llm_options": llm_options,
                "prompt_version": self._prompt_version(body, provider),
                "input_hash": input_hash,
                "source_ids": body.source_ids,
                "period_start": body.period_start,
                "period_end": body.period_end,
                "status": "queued",
                "created_at": time.time(),
            }
        )

        if self._arbiter is None:
            threading.Thread(
                target=self._run,
                args=(job_id, run_id, body, on_terminal),
                daemon=True,
            ).start()
            return {
                "job_id": job_id,
                "analysis_run_id": run_id,
                "status": "queued",
            }

        try:
            self._arbiter.submit(
                task_id=job_id,
                workload_type=ANALYSIS_JOB_TYPE,
                run=lambda: self._run(job_id, run_id, body, on_terminal),
                on_cancel=lambda _reason: self._cancel_before_start(job_id, run_id, on_terminal),
                on_reject=lambda reason: self._reject_before_start(job_id, run_id, reason, on_terminal),
            )
            status = "queued"
        except (WorkloadQueueFull, WorkloadArbiterClosed, WorkloadAdmissionRejected) as exc:
            self._reject_before_start(job_id, run_id, str(exc), on_terminal)
            status = "failed"
        return {
            "job_id": job_id,
            "analysis_run_id": run_id,
            "status": status,
        }

    def create_pipeline(
        self,
        body: AnalysisPipelineRequest,
        *,
        on_terminal: AnalysisTerminalCallback | None = None,
    ) -> dict[str, Any]:
        pipeline = get_pipeline(body.pipeline_id)
        pipeline_run_id = str(uuid.uuid4())
        templates = self._execution_templates(body, pipeline)
        jobs = []
        for template in templates:
            llm_options = self._request_llm_options(body)
            request_body = AnalysisRequest(
                transcription_id=body.transcription_id,
                recording_id=body.recording_id,
                text=body.text,
                **llm_options,
                analysis_type=template.analysis_type,
                template_id=template.id,
                template_version=template.version,
                pipeline_id=pipeline.id,
                pipeline_run_id=pipeline_run_id,
                source_ids=body.source_ids,
                period_start=body.period_start,
                period_end=body.period_end,
            )
            jobs.append(self.create(request_body, on_terminal=on_terminal))
        return {
            "pipeline_run_id": pipeline_run_id,
            "pipeline_id": pipeline.id,
            "status": "queued",
            "jobs": jobs,
        }

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        existing = self._store.get(job_id)
        if existing is None or existing["type"] != ANALYSIS_JOB_TYPE:
            return existing
        if existing["status"] in TERMINAL_JOB_STATUSES:
            return existing
        requested = self._store.request_cancel(job_id)
        if self._arbiter is not None:
            self._arbiter.cancel_pending(job_id)
        return self._store.get(job_id) or requested

    def pipeline_identity(self, body: AnalysisPipelineRequest) -> dict[str, Any]:
        """Return the non-secret durable identity of an analysis pipeline request."""
        pipeline = get_pipeline(body.pipeline_id)
        templates = self._execution_templates(body, pipeline)
        settings = AnalysisService.settings_with_request_overrides(load_settings(), body)
        provider = settings.get("llm_provider", "mock")
        effective_model = self._effective_model(provider, settings)
        return {
            "pipeline_id": pipeline.id,
            "templates": [
                {
                    "id": template.id,
                    "analysis_type": template.analysis_type,
                    "version": template.version,
                }
                for template in templates
            ],
            "llm": self._llm_options(settings, provider=provider, model=effective_model),
        }

    def _execution_templates(
        self,
        body: AnalysisPipelineRequest,
        pipeline: AnalysisPipeline,
    ) -> list[AnalysisTemplate]:
        if body.analysis_types:
            return [template_for_analysis_type(analysis_type) for analysis_type in body.analysis_types]
        if pipeline.id == DEFAULT_PIPELINE_ID:
            return [get_template(SHARED_NOTES_TEMPLATE_ID)]
        return [get_template(template_id) for template_id in pipeline.template_ids]

    def _run(
        self,
        job_id: str,
        run_id: str,
        body: AnalysisRequest,
        on_terminal: AnalysisTerminalCallback | None = None,
    ) -> None:
        try:
            if self._store.get(job_id) and self._store.get(job_id).get("cancel_requested"):
                self._mark_cancelled(job_id, run_id)
                return
            self._store.update(job_id, status="running", current_step="analysis", progress=10)
            self._services.catalog.update_analysis_run(run_id, status="running")
            result = AnalysisService(self._services).analyze(body)
            if self._store.get(job_id) and self._store.get(job_id).get("cancel_requested"):
                self._mark_cancelled(job_id, run_id)
                return
            self._services.catalog.update_analysis_run(
                run_id,
                status="completed",
                result=result,
                completed_at=time.time(),
            )
            self._store.update(
                job_id,
                status="completed",
                current_step="completed",
                progress=100,
                result={"analysis_run_id": run_id, "analysis": result},
            )
        except HTTPException as exc:
            self._mark_failed(job_id, run_id, str(exc.detail))
        except Exception as exc:
            self._mark_failed(job_id, run_id, str(exc))
        finally:
            current = self._store.get(job_id)
            if current and current["status"] in TERMINAL_JOB_STATUSES:
                self._notify_terminal(job_id, on_terminal)

    def _cancel_before_start(
        self,
        job_id: str,
        run_id: str,
        on_terminal: AnalysisTerminalCallback | None,
    ) -> None:
        self._mark_cancelled(job_id, run_id)
        self._notify_terminal(job_id, on_terminal)

    def _reject_before_start(
        self,
        job_id: str,
        run_id: str,
        reason: str,
        on_terminal: AnalysisTerminalCallback | None,
    ) -> None:
        self._mark_failed(job_id, run_id, reason)
        self._notify_terminal(job_id, on_terminal)

    def _notify_terminal(
        self,
        job_id: str,
        callback: AnalysisTerminalCallback | None,
    ) -> None:
        if callback is None:
            return
        try:
            snapshot = self._store.get(job_id)
            if snapshot is not None:
                callback(snapshot)
        except Exception:
            logger.exception("Analysis terminal callback failed for job %s", job_id)

    def _mark_cancelled(self, job_id: str, run_id: str) -> None:
        current = self._store.get(job_id)
        if current and current["status"] in TERMINAL_JOB_STATUSES:
            return
        self._services.catalog.update_analysis_run(
            run_id,
            status="cancelled",
            completed_at=time.time(),
        )
        self._store.update(job_id, status="cancelled", current_step="cancelled")

    def _mark_failed(self, job_id: str, run_id: str, error: str) -> None:
        current = self._store.get(job_id)
        if current and current["status"] in TERMINAL_JOB_STATUSES:
            return
        error = error[:2000]
        self._services.catalog.update_analysis_run(
            run_id,
            status="failed",
            error=error,
            completed_at=time.time(),
        )
        self._store.update(job_id, status="failed", current_step="failed", error=error)

    def _resolve_scope(self, body: AnalysisRequest, run_id: str) -> tuple[str, str]:
        if body.transcription_id:
            return "transcription", body.transcription_id
        if body.recording_id:
            return "recording", body.recording_id
        return "inline_text", run_id

    def _request_payload(self, body: AnalysisRequest) -> dict[str, Any]:
        if hasattr(body, "model_dump"):
            return body.model_dump()
        return body.dict()

    def _replace_request(self, body: AnalysisRequest, **updates: Any) -> AnalysisRequest:
        if hasattr(body, "model_copy"):
            return body.model_copy(update=updates)
        return body.copy(update=updates)

    def _with_template_defaults(self, body: AnalysisRequest) -> AnalysisRequest:
        if body.prompt:
            return self._replace_request(
                body,
                analysis_type=body.analysis_type or "custom_question",
                template_id=body.template_id or "custom_question",
                template_version=body.template_version or DEFAULT_TEMPLATE_VERSION,
            )
        template = get_template(body.template_id) if body.template_id else template_for_analysis_type(body.analysis_type)
        prompt = template.prompt
        if body.question:
            prompt = f"{prompt}\n\nDomanda dell'utente: {body.question}"
        return self._replace_request(
            body,
            prompt=prompt,
            analysis_type=template.analysis_type,
            template_id=template.id,
            template_version=template.version,
        )

    def _with_recording_transcription(self, body: AnalysisRequest) -> AnalysisRequest:
        if body.transcription_id or not body.recording_id:
            return body
        try:
            transcription = self._services.transcriptions.find_for_recording(body.recording_id)
        except Exception:
            transcription = None
        if not transcription:
            return body
        return self._replace_request(body, transcription_id=transcription.get("id"))

    def _input_hash(self, body: AnalysisRequest, payload: dict[str, Any]) -> str:
        if body.transcription_id:
            try:
                text = self._services.transcriptions.get(body.transcription_id).get("text", "")
            except Exception:
                text = body.transcription_id
        elif body.text:
            text = body.text
        elif body.recording_id:
            text = body.recording_id
        else:
            text = repr(payload)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _request_llm_options(self, body: AnalysisPipelineRequest) -> dict[str, Any]:
        options: dict[str, Any] = {}
        provided_fields = getattr(body, "model_fields_set", None)
        if provided_fields is None:
            provided_fields = getattr(body, "__fields_set__", None)
        tracks_provided_fields = provided_fields is not None
        provided_fields = provided_fields or set()
        for field in ANALYSIS_LLM_REQUEST_FIELDS:
            if tracks_provided_fields and field not in provided_fields:
                continue
            value = getattr(body, field, None)
            if value is None:
                if tracks_provided_fields:
                    options[field] = None
                continue
            if isinstance(value, str) and not value.strip():
                continue
            options[field] = value
        return options

    def _effective_model(self, provider: str, settings: dict[str, Any]) -> str:
        if provider == "gemini":
            return settings.get("gemini_model") or DEFAULT_GEMINI_MODEL
        if provider in {"nemotron_local", "voxtral_local"}:
            return settings.get("local_llm_model") or ""
        return ""

    def _llm_options(self, settings: dict[str, Any], *, provider: str, model: str) -> dict[str, Any]:
        model_path = resolve_local_llm_model_path(settings, model)
        return {
            "provider": provider,
            "model": model,
            "mode": settings.get("local_llm_mode") or "auto",
            "url": settings.get("local_llm_url") or "",
            "quality_preset": settings.get("local_llm_quality_preset") or "balanced",
            "temperature": settings.get("local_llm_temperature"),
            "reasoning": settings.get("local_llm_reasoning") or "auto",
            "show_thinking": False,
            "max_output_tokens": settings.get("local_llm_max_output_tokens"),
            "json_mode": settings.get("local_llm_json_mode", True),
            "backend": settings.get("local_llm_backend") or "",
            "model_path": model_path,
            "mmproj_path": settings.get("local_llm_mmproj_path") or "",
            "ctx_size": settings.get("local_llm_ctx_size"),
        }

    def _prompt_version(self, body: AnalysisRequest, provider: str) -> str:
        if body.prompt:
            return f"{body.template_id or 'custom'}_{body.template_version or DEFAULT_TEMPLATE_VERSION}"
        if body.recording_id and provider == "voxtral_local":
            return "voxtral_audio_analysis_v1"
        return "summary_v1"
