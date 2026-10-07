from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from local_asr_server.app_services import AppServices
from local_asr_server.asr_provider import ASR_PROVIDER_LOCAL
from local_asr_server.jobs.models import TERMINAL_JOB_STATUSES
from local_asr_server.schemas import AnalysisPipelineRequest, TranscriptionJobRequest
from local_asr_server.settings import load_settings
from local_asr_server.transcription_diarization import DIARIZATION_PROVIDER_DISABLED
from local_asr_server.transcription_jobs import (
    DIARIZATION_JOB_TYPE,
    TRANSCRIPTION_JOB_TYPE,
    VISUAL_INTELLIGENCE_JOB_TYPE,
)
from local_asr_server.visual_intelligence.service import visual_processing_identity


MEETING_PREPARATION_JOB_TYPE = "meeting_preparation"
MEETING_PREPARATION_PIPELINE = "meeting_default"
PREPARATION_RESULT_VERSION = 4

logger = logging.getLogger("uvicorn.error")
TerminalCallback = Callable[[dict[str, Any]], None]
StartTranscription = Callable[[TerminalCallback], dict[str, Any]]
StartPipeline = Callable[[str, TerminalCallback], dict[str, Any]]
StartVisual = Callable[[str, TerminalCallback], dict[str, Any]]


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class MeetingPreparationManager:
    """Persisted coordinator for the existing transcription and analysis jobs.

    This class does not schedule heavy work. It only creates durable parent state,
    links child jobs, and advances stages from terminal callbacks emitted by the
    existing managers that already use HeavyWorkloadArbiter.
    """

    def __init__(self, services: AppServices, *, default_model: str) -> None:
        self.services = services
        self.default_model = default_model

    def create(
        self,
        recording_id: str,
        *,
        start_transcription: StartTranscription,
        start_pipeline: StartPipeline,
        start_visual: StartVisual | None = None,
        include_screenshots: bool = True,
    ) -> dict[str, Any]:
        # Resolve the recording before creating durable work so a bad id cannot
        # leave an orphan parent job.
        self.services.recordings.get(recording_id, include_result=False)
        transcription_request = TranscriptionJobRequest(visual_intelligence_enabled=False)
        screenshots = self.services.recordings.list_screenshots(recording_id)
        selected_screenshots = screenshots if include_screenshots else []
        available_screenshots = [item for item in selected_screenshots if item.get("available")]
        screenshot_source_snapshot = [
            {
                "screenshot_id": item.get("screenshot_id"),
                "sha256": item.get("sha256"),
                "timestamp": item.get("timestamp"),
                "available": bool(item.get("available")),
            }
            for item in selected_screenshots
        ]
        list_notes = getattr(self.services.recordings, "list_notes", None)
        user_notes = list_notes(recording_id) if callable(list_notes) else []
        user_note_source_snapshot = [
            {
                "note_id": item.get("note_id"),
                "timestamp": item.get("timestamp"),
                "revision": item.get("revision"),
                "text_sha256": hashlib.sha256(
                    str(item.get("text") or "").encode("utf-8")
                ).hexdigest(),
            }
            for item in user_notes
        ]
        audio_source_identity = self._audio_source_identity(recording_id)
        source_identity = self._source_identity(
            recording_id,
            audio_source_identity=audio_source_identity,
            screenshots=selected_screenshots,
            user_notes=user_notes,
        )
        visual_material = (
            visual_processing_identity(load_settings())
            if available_screenshots
            else {
                "version": 1,
                "status": "excluded" if not include_screenshots else "not_applicable",
            }
        )
        visual_identity = _hash_json(visual_material)
        asr_identity, asr_material = self._asr_identity(transcription_request)
        analysis_request = AnalysisPipelineRequest(
            recording_id=recording_id,
            pipeline_id=MEETING_PREPARATION_PIPELINE,
        )
        analysis_material = self.services.analysis_jobs.pipeline_identity(analysis_request)
        analysis_identity = _hash_json(analysis_material)
        preparation_key = _hash_json(
            {
                "version": PREPARATION_RESULT_VERSION,
                "recording_id": recording_id,
                "include_screenshots": include_screenshots,
                "source_identity": source_identity,
                "asr_identity": asr_identity,
                "visual_identity": visual_identity,
                "analysis_identity": analysis_identity,
            }
        )

        completed = self.services.jobs.find_latest(
            job_type=MEETING_PREPARATION_JOB_TYPE,
            scope_type="recording",
            scope_id=recording_id,
            dedupe_key=preparation_key,
            statuses=["completed"],
        )
        if completed is not None:
            return {**completed, "deduplicated": True, "reused_completed": True}

        previous = self.services.jobs.find_latest(
            job_type=MEETING_PREPARATION_JOB_TYPE,
            scope_type="recording",
            scope_id=recording_id,
            dedupe_key=preparation_key,
            statuses=["failed", "interrupted", "cancelled"],
        )
        parent, created = self.services.jobs.create_or_get_active(
            job_id=str(uuid.uuid4()),
            job_type=MEETING_PREPARATION_JOB_TYPE,
            scope_type="recording",
            scope_id=recording_id,
            dedupe_key=preparation_key,
            payload={
                "recording_id": recording_id,
                "pipeline_id": MEETING_PREPARATION_PIPELINE,
                "preparation_key": preparation_key,
                "include_screenshots": include_screenshots,
                "screenshot_count": len(selected_screenshots),
                "user_note_count": len(user_notes),
            },
            current_step="preparing_transcript",
            progress=5,
        )
        if not created:
            return {**parent, "deduplicated": True, "reused_completed": False}

        result = {
            "version": PREPARATION_RESULT_VERSION,
            "preparation_key": preparation_key,
            "source_identity": source_identity,
            "audio_source_identity": audio_source_identity,
            "include_screenshots": include_screenshots,
            "screenshot_count": len(selected_screenshots),
            "available_screenshot_count": len(available_screenshots),
            "screenshot_source_snapshot": screenshot_source_snapshot,
            "user_note_count": len(user_notes),
            "user_note_source_snapshot": user_note_source_snapshot,
            "asr_identity": asr_identity,
            "visual_identity": visual_identity,
            "analysis_identity": analysis_identity,
            "pipeline_id": MEETING_PREPARATION_PIPELINE,
            "transcription_id": None,
            "transcription_job_id": None,
            "pipeline_run_id": None,
            "analysis_job_ids": [],
            "analysis_launch_complete": False,
            "visual_job_id": None,
            "visual_status": "not_requested",
            "warnings": [],
            "resumed_from_job_id": previous["id"] if previous is not None else None,
        }
        self.services.jobs.update(
            parent["id"],
            status="running",
            current_step="preparing_transcript",
            progress=5,
            result=result,
            event_payload={"phase": "transcript"},
            progress_detail={"phase": "transcript"},
        )

        reusable = self._reusable_transcription(
            recording_id,
            audio_source_identity=audio_source_identity,
            asr_identity=asr_identity,
            asr_material=asr_material,
        )
        if reusable is not None:
            self._merge_result(parent["id"], transcription_id=reusable["id"])
            self._start_visual_or_analysis(
                parent["id"], reusable["id"], start_pipeline, start_visual,
            )
            return self.services.jobs.get(parent["id"]) or parent

        try:
            child = start_transcription(
                lambda snapshot: self._on_transcription_terminal(
                    parent["id"], snapshot, start_pipeline, start_visual,
                )
            )
            self.services.jobs.link_child(
                parent["id"], child["id"], stage="transcription", ordinal=0,
            )
            self._merge_result(parent["id"], transcription_job_id=child["id"])
            self._cancel_child_if_parent_cancelled(parent["id"], child)
        except Exception as exc:
            self._fail_parent(parent["id"], f"Unable to start transcription: {exc}")
        return self.services.jobs.get(parent["id"]) or parent

    def cancel(self, parent_job_id: str) -> dict[str, Any] | None:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None or parent["type"] != MEETING_PREPARATION_JOB_TYPE:
            return None
        if parent["status"] in TERMINAL_JOB_STATUSES:
            return parent

        self.services.jobs.request_cancel(parent_job_id)
        active_children = []
        for child in self.services.jobs.list_children(parent_job_id):
            if child["status"] in TERMINAL_JOB_STATUSES:
                continue
            active_children.append(child)
            self._cancel_child(child)

        if not active_children:
            self.services.jobs.update(
                parent_job_id,
                status="cancelled",
                current_step="cancelled",
                progress=parent.get("progress") or 0,
                cancel_requested=True,
            )
        return self.services.jobs.get(parent_job_id)

    def _cancel_child(self, child: dict[str, Any]) -> None:
        if child["status"] in TERMINAL_JOB_STATUSES:
            return
        if child["type"] == "analysis":
            self.services.analysis_jobs.cancel(child["id"])
        elif child["type"] in {
            TRANSCRIPTION_JOB_TYPE,
            DIARIZATION_JOB_TYPE,
            VISUAL_INTELLIGENCE_JOB_TYPE,
        }:
            self.services.transcription_jobs.cancel(child["id"])
        else:
            self.services.jobs.request_cancel(child["id"])

    def _cancel_child_if_parent_cancelled(
        self,
        parent_job_id: str,
        child: dict[str, Any],
    ) -> None:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None:
            return
        if parent.get("cancel_requested") or parent["status"] == "cancelled":
            current_child = self.services.jobs.get(child["id"]) or child
            self._cancel_child(current_child)

    def _on_transcription_terminal(
        self,
        parent_job_id: str,
        child: dict[str, Any],
        start_pipeline: StartPipeline,
        start_visual: StartVisual | None = None,
    ) -> None:
        self.services.jobs.link_child(
            parent_job_id, child["id"], stage="transcription", ordinal=0,
        )
        parent = self.services.jobs.get(parent_job_id)
        if parent is None or parent["status"] in TERMINAL_JOB_STATUSES:
            return
        if parent.get("cancel_requested"):
            self.services.jobs.update(
                parent_job_id,
                status="cancelled",
                current_step="cancelled",
                progress=parent.get("progress") or 0,
                cancel_requested=True,
            )
            return
        if child["status"] != "completed":
            self._fail_parent(
                parent_job_id,
                child.get("error") or f"Transcription ended as {child['status']}",
            )
            return
        transcription_id = (child.get("result") or {}).get("saved_id")
        if not transcription_id:
            self._fail_parent(parent_job_id, "Transcription completed without a persisted result")
            return
        self._merge_result(
            parent_job_id,
            transcription_id=transcription_id,
            transcription_job_id=child["id"],
        )
        self._start_visual_or_analysis(
            parent_job_id, transcription_id, start_pipeline, start_visual,
        )

    def _start_visual_or_analysis(
        self,
        parent_job_id: str,
        transcription_id: str,
        start_pipeline: StartPipeline,
        start_visual: StartVisual | None,
    ) -> None:
        parent = self.services.jobs.get(parent_job_id)
        recording_id = (parent or {}).get("scope_id") or ""
        result = (parent or {}).get("result") or {}
        if not result.get("include_screenshots", True):
            self._merge_result(parent_job_id, visual_status="excluded")
            self._start_analysis(parent_job_id, transcription_id, start_pipeline)
            return
        screenshots = self.services.recordings.list_screenshots(recording_id)
        current_by_id = {
            str(item.get("screenshot_id")): item
            for item in screenshots
            if item.get("screenshot_id")
        }
        selected_snapshot = [
            item for item in result.get("screenshot_source_snapshot") or []
            if isinstance(item, dict) and item.get("screenshot_id")
        ]
        if selected_snapshot:
            selected = []
            unavailable_selected = []
            for snapshot in selected_snapshot:
                screenshot_id = str(snapshot["screenshot_id"])
                current = current_by_id.get(screenshot_id)
                expected_sha = str(snapshot.get("sha256") or "")
                current_sha = str((current or {}).get("sha256") or "")
                if (
                    current is None
                    or not current.get("available")
                    or (expected_sha and current_sha and expected_sha != current_sha)
                ):
                    unavailable_selected.append(screenshot_id)
                    continue
                selected.append(current)
            screenshots = selected
        else:
            unavailable_selected = [
                str(item.get("screenshot_id"))
                for item in screenshots
                if item.get("screenshot_id") and not item.get("available")
            ]
        available = [item for item in screenshots if item.get("available")]
        if unavailable_selected:
            self._append_warning(
                parent_job_id,
                f"screenshot_sources_unavailable:{len(unavailable_selected)}",
            )
        if unavailable_selected and not available:
            self._append_warning(parent_job_id, "screenshot_assets_unavailable")
            self._merge_result(parent_job_id, visual_status="skipped_assets_unavailable")
            self._start_analysis(parent_job_id, transcription_id, start_pipeline)
            return
        if start_visual is None or not screenshots:
            self._start_analysis(parent_job_id, transcription_id, start_pipeline)
            return

        if self._reuse_completed_visual_stage(parent_job_id):
            self._start_analysis(parent_job_id, transcription_id, start_pipeline)
            return

        parent = self.services.jobs.get(parent_job_id)
        if parent is None or parent["status"] in TERMINAL_JOB_STATUSES:
            return
        if parent.get("cancel_requested"):
            self.services.jobs.update(
                parent_job_id,
                status="cancelled",
                current_step="cancelled",
                progress=parent.get("progress") or 0,
                cancel_requested=True,
            )
            return

        self.services.jobs.update(
            parent_job_id,
            status="running",
            current_step="preparing_visual_evidence",
            progress=45,
            result=parent.get("result"),
            event_payload={
                "phase": "visual",
                "transcription_id": transcription_id,
                "screenshot_count": len(selected_snapshot) if selected_snapshot else len(screenshots),
                "available_screenshot_count": len(available),
            },
            progress_detail={
                "phase": "visual",
                "screenshot_count": len(selected_snapshot) if selected_snapshot else len(screenshots),
                "available_screenshot_count": len(available),
            },
        )
        try:
            child = start_visual(
                transcription_id,
                lambda snapshot: self._on_visual_terminal(
                    parent_job_id, snapshot, transcription_id, start_pipeline,
                ),
            )
            self.services.jobs.link_child(
                parent_job_id, child["id"], stage="visual", ordinal=0,
            )
            self._merge_result(
                parent_job_id,
                visual_job_id=child["id"],
                visual_status=child.get("status") or "queued",
            )
            self._cancel_child_if_parent_cancelled(parent_job_id, child)
        except Exception as exc:
            logger.warning(
                "Visual evidence stage could not start for preparation %s: %s",
                parent_job_id,
                exc,
            )
            self._append_warning(parent_job_id, f"visual_stage_not_started:{exc}")
            self._merge_result(parent_job_id, visual_status="failed_to_start")
            self._start_analysis(parent_job_id, transcription_id, start_pipeline)

    def _on_visual_terminal(
        self,
        parent_job_id: str,
        child: dict[str, Any],
        transcription_id: str,
        start_pipeline: StartPipeline,
    ) -> None:
        self.services.jobs.link_child(
            parent_job_id, child["id"], stage="visual", ordinal=0,
        )
        parent = self.services.jobs.get(parent_job_id)
        if parent is None or parent["status"] in TERMINAL_JOB_STATUSES:
            return
        if parent.get("cancel_requested"):
            self.services.jobs.update(
                parent_job_id,
                status="cancelled",
                current_step="cancelled",
                progress=parent.get("progress") or 0,
                cancel_requested=True,
            )
            return

        if child.get("status") == "completed":
            self._merge_result(
                parent_job_id,
                visual_job_id=child["id"],
                visual_status=(child.get("result") or {}).get("outcome_status") or "completed",
            )
        else:
            self._append_warning(
                parent_job_id,
                child.get("error") or f"visual_stage_{child.get('status') or 'failed'}",
            )
            self._merge_result(
                parent_job_id,
                visual_job_id=child["id"],
                visual_status=child.get("status") or "failed",
            )
        self._start_analysis(parent_job_id, transcription_id, start_pipeline)

    def _start_analysis(
        self,
        parent_job_id: str,
        transcription_id: str,
        start_pipeline: StartPipeline,
    ) -> None:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None or parent["status"] in TERMINAL_JOB_STATUSES:
            return
        if parent.get("cancel_requested"):
            self.services.jobs.update(
                parent_job_id,
                status="cancelled",
                current_step="cancelled",
                progress=parent.get("progress") or 0,
                cancel_requested=True,
            )
            return

        self._merge_result(
            parent_job_id,
            transcription_id=transcription_id,
            analysis_launch_complete=False,
        )
        self.services.jobs.update(
            parent_job_id,
            status="running",
            current_step="preparing_notes",
            progress=60,
            result=(self.services.jobs.get(parent_job_id) or {}).get("result"),
            event_payload={"phase": "notes", "transcription_id": transcription_id},
            progress_detail={"phase": "notes", "transcription_id": transcription_id},
        )
        try:
            pipeline = start_pipeline(
                transcription_id,
                lambda snapshot: self._on_analysis_terminal(parent_job_id, snapshot),
            )
            analysis_job_ids = []
            for index, child in enumerate(pipeline.get("jobs") or []):
                child_id = child.get("job_id") or child.get("id")
                if not child_id:
                    continue
                analysis_job_ids.append(child_id)
                self.services.jobs.link_child(
                    parent_job_id, child_id, stage="analysis", ordinal=index,
                )
                child_snapshot = self.services.jobs.get(child_id) or {
                    "id": child_id,
                    "type": "analysis",
                    "status": child.get("status") or "queued",
                }
                self._cancel_child_if_parent_cancelled(parent_job_id, child_snapshot)
            self._merge_result(
                parent_job_id,
                pipeline_run_id=pipeline.get("pipeline_run_id"),
                analysis_job_ids=analysis_job_ids,
                analysis_launch_complete=True,
            )
            self._reconcile_analysis(parent_job_id)
        except Exception as exc:
            self._fail_parent(parent_job_id, f"Unable to start notes analysis: {exc}")

    def _on_analysis_terminal(self, parent_job_id: str, child: dict[str, Any]) -> None:
        self.services.jobs.link_child(
            parent_job_id,
            child["id"],
            stage="analysis",
            ordinal=self._analysis_ordinal(parent_job_id, child["id"]),
        )
        self._reconcile_analysis(parent_job_id)

    def _reconcile_analysis(self, parent_job_id: str) -> None:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None or parent["status"] in TERMINAL_JOB_STATUSES:
            return
        result = parent.get("result") or {}
        if not result.get("analysis_launch_complete"):
            return
        children = self.services.jobs.list_children(parent_job_id, stage="analysis")
        if not children:
            self._fail_parent(parent_job_id, "Notes pipeline did not create analysis jobs")
            return
        if any(child["status"] not in TERMINAL_JOB_STATUSES for child in children):
            return
        if parent.get("cancel_requested"):
            self.services.jobs.update(
                parent_job_id,
                status="cancelled",
                current_step="cancelled",
                progress=90,
                result=result,
                cancel_requested=True,
            )
            return
        failed = [child for child in children if child["status"] != "completed"]
        if failed:
            summary = "; ".join(
                f"{child['id'][:8]}:{child['status']}" for child in failed[:4]
            )
            self._fail_parent(parent_job_id, f"Notes analysis incomplete ({summary})")
            return
        self.services.jobs.update(
            parent_job_id,
            status="completed",
            current_step="completed",
            progress=100,
            result=result,
            event_payload={
                "phase": "completed",
                "transcription_id": result.get("transcription_id"),
                "pipeline_run_id": result.get("pipeline_run_id"),
            },
            progress_detail={"phase": "completed"},
        )

    def _analysis_ordinal(self, parent_job_id: str, child_job_id: str) -> int:
        current = self.services.jobs.list_children(parent_job_id, stage="analysis")
        for child in current:
            if child["id"] == child_job_id:
                return int(child.get("link_ordinal") or 0)
        return len(current)


    def _reuse_completed_visual_stage(self, parent_job_id: str) -> bool:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None:
            return False
        previous_id = (parent.get("result") or {}).get("resumed_from_job_id")
        if not previous_id:
            return False
        previous = self.services.jobs.get(previous_id)
        previous_result = (previous or {}).get("result") or {}
        visual_job_id = previous_result.get("visual_job_id")
        if not visual_job_id:
            return False
        visual_job = self.services.jobs.get(visual_job_id)
        if visual_job is None or visual_job.get("status") != "completed":
            return False
        outcome = (visual_job.get("result") or {}).get("outcome_status") or "completed"
        self._merge_result(
            parent_job_id,
            visual_job_id=visual_job_id,
            visual_status=f"reused_{outcome}",
        )
        for warning in previous_result.get("warnings") or []:
            self._append_warning(parent_job_id, str(warning))
        return True

    def _append_warning(self, parent_job_id: str, warning: str) -> None:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None:
            return
        result = dict(parent.get("result") or {})
        warnings = list(result.get("warnings") or [])
        if warning not in warnings:
            warnings.append(warning[:500])
        self._merge_result(parent_job_id, warnings=warnings)

    def _merge_result(self, parent_job_id: str, **updates: Any) -> dict[str, Any] | None:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None:
            return None
        result = {**(parent.get("result") or {}), **updates}
        return self.services.jobs.update(
            parent_job_id,
            status=parent["status"],
            current_step=parent.get("current_step"),
            progress=parent.get("progress"),
            result=result,
            cancel_requested=parent.get("cancel_requested"),
            progress_detail=parent.get("progress_detail"),
        )

    def _fail_parent(self, parent_job_id: str, error: str) -> None:
        parent = self.services.jobs.get(parent_job_id)
        if parent is None or parent["status"] in TERMINAL_JOB_STATUSES:
            return
        self.services.jobs.update(
            parent_job_id,
            status="failed",
            current_step="preparation_failed",
            progress=parent.get("progress") or 0,
            result=parent.get("result"),
            error=error[:2000],
            event_payload={"phase": "failed"},
            progress_detail={"phase": "failed"},
        )

    def _audio_source_identity(self, recording_id: str) -> str:
        """Stable ASR source identity. Visual evidence must never invalidate it."""
        tracks = []
        for track, audio_path in self.services.recordings.transcribable_tracks(recording_id):
            chunks = track.get("chunks") or []
            use_chunk_identity = bool(chunks) and all(item.get("sha256") for item in chunks)
            source = {
                "track_id": track.get("id"),
                "source": track.get("source"),
                "bytes_written": track.get("bytes_written"),
                "chunk_count": track.get("chunk_count"),
            }
            if use_chunk_identity:
                source["chunks"] = [
                    {
                        "sequence": item.get("sequence"),
                        "sha256": item.get("sha256"),
                        "size": item.get("size"),
                    }
                    for item in chunks
                ]
            else:
                source["sha256"] = _hash_file(audio_path)
            tracks.append(source)
        # Keep the pre-screenshot v1 material exactly stable for backward reuse.
        return _hash_json({"version": 1, "tracks": tracks})

    def _source_identity(
        self,
        recording_id: str,
        *,
        audio_source_identity: str | None = None,
        screenshots: list[dict[str, Any]] | None = None,
        user_notes: list[dict[str, Any]] | None = None,
    ) -> str:
        screenshots = screenshots if screenshots is not None else self.services.recordings.list_screenshots(recording_id)
        user_notes = user_notes if user_notes is not None else self.services.recordings.list_notes(recording_id)
        screenshot_material = [
            {
                "screenshot_id": item.get("screenshot_id"),
                "sequence": item.get("sequence"),
                "timestamp": item.get("timestamp"),
                "sha256": item.get("sha256"),
                "display_id": item.get("display_id"),
                "capture_kind": item.get("capture_kind"),
                "available": item.get("available"),
            }
            for item in screenshots
        ]
        user_note_material = [
            {
                "note_id": item.get("note_id"),
                "timestamp": item.get("timestamp"),
                "revision": item.get("revision"),
                "text_sha256": hashlib.sha256(
                    str(item.get("text") or "").encode("utf-8")
                ).hexdigest(),
            }
            for item in user_notes
        ]
        return _hash_json({
            "version": 3,
            "audio_source_identity": (
                audio_source_identity or self._audio_source_identity(recording_id)
            ),
            "screenshots": screenshot_material,
            "user_notes": user_note_material,
        })

    def _asr_identity(
        self,
        body: TranscriptionJobRequest,
    ) -> tuple[str, dict[str, Any]]:
        settings = load_settings()
        provider, provider_model, _provider_options, public_options = self.services.transcription.resolve_asr(
            settings,
            provider=body.asr_provider,
            model=body.model or self.default_model,
            speechmatics_region=body.speechmatics_region,
            speechmatics_model=body.speechmatics_model,
            speechmatics_diarization=body.speechmatics_diarization,
        )
        target_model = provider_model or body.model or self.default_model
        diarization_provider = (
            ASR_PROVIDER_LOCAL
            if settings.get("speaker_diarization_enabled", False)
            else DIARIZATION_PROVIDER_DISABLED
        )
        material = {
            "version": 1,
            "provider": provider,
            "model": target_model,
            "language": body.language,
            "task": body.task,
            "word_timestamps": body.word_timestamps,
            "initial_prompt": body.initial_prompt,
            "temperature": body.temperature,
            "condition_on_previous_text": body.condition_on_previous_text,
            "vad_guided": body.vad_guided,
            "vad_post_filter": body.vad_post_filter,
            "provider_options": public_options,
            "diarization_provider": diarization_provider,
            "visual_intelligence_enabled": False,
        }
        return _hash_json(material), material

    def _reusable_transcription(
        self,
        recording_id: str,
        *,
        audio_source_identity: str,
        asr_identity: str,
        asr_material: dict[str, Any],
    ) -> dict[str, Any] | None:
        transcription = self.services.transcriptions.find_for_recording(recording_id)
        if transcription is None:
            return None
        transcription_id = transcription.get("id")
        for preparation in self.services.jobs.list_jobs(
            job_type=MEETING_PREPARATION_JOB_TYPE,
            scope_type="recording",
            scope_id=recording_id,
            limit=100,
        ):
            result = preparation.get("result") or {}
            if result.get("transcription_id") != transcription_id:
                continue
            prior_audio_identity = result.get("audio_source_identity")
            if prior_audio_identity is None and int(result.get("version") or 1) < 2:
                # v1 preparation source_identity contained audio only.
                prior_audio_identity = result.get("source_identity")
            if (
                prior_audio_identity == audio_source_identity
                and result.get("asr_identity") == asr_identity
            ):
                return transcription
            return None
        return transcription if self._legacy_transcription_matches(transcription, asr_material) else None

    @staticmethod
    def _legacy_transcription_matches(
        transcription: dict[str, Any],
        material: dict[str, Any],
    ) -> bool:
        if transcription.get("asr_provider") != material.get("provider"):
            return False
        if transcription.get("model") != material.get("model"):
            return False
        actual_options = transcription.get("provider_options") or {}
        if _hash_json(actual_options) != _hash_json(material.get("provider_options") or {}):
            return False
        expected_language = material.get("language")
        if expected_language and transcription.get("language") not in {expected_language, None, ""}:
            return False
        diarization = (transcription.get("stats") or {}).get("speaker_diarization") or {}
        expected_diarization = material.get("diarization_provider")
        if expected_diarization == DIARIZATION_PROVIDER_DISABLED:
            return diarization.get("status") in {None, "", "disabled"}
        return diarization.get("provider") == expected_diarization and diarization.get("status") != "disabled"
