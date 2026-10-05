from __future__ import annotations

from local_asr_server.app_services import get_services

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from local_asr_server.recordings import RecordingConflict, RecordingNotFound
from local_asr_server.transcription_jobs import (
    DIARIZATION_JOB_TYPE,
    TRANSCRIPTION_JOB_TYPE,
    TranscriptionJob,
)
from local_asr_server.settings import load_settings
from local_asr_server.env import get_env_var
from local_asr_server.services.transcription_service import TranscriptionService
from local_asr_server.services.transcription_application import (
    SingleFileTranscriptionRequest,
    SingleFileTranscriptionUseCase,
)
from local_asr_server.transcriber import (
    str_to_bool,
    get_cached_result,
    transcribe_file_sync,
    transcribe_stream_generator,
    VAD_GUIDED_DEFAULT,
    VAD_POST_FILTER_DEFAULT,
)
from local_asr_server.schemas import (
    TranscribePathRequest,
    TranscribeRecordingRequest,
    TranscriptionJobRequest,
    DiarizationJobRequest,
    MergeTranscriptionsRequest,
    AnalysisPipelineRequest,
)
from local_asr_server.routers.helpers import _build_projects
from local_asr_server.asr_provider import ASR_PROVIDER_LOCAL
from local_asr_server.transcription_diarization import (
    DIARIZATION_PROVIDER_DISABLED,
    DIARIZATION_PROVIDERS,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class SpeakerNamesRequest(BaseModel):
    names: dict[str, str] = Field(default_factory=dict)


def _get_transcribe_file_sync():
    import sys
    server_mod = sys.modules.get("local_asr_server.server")
    if server_mod and hasattr(server_mod, "transcribe_file_sync"):
        return server_mod.transcribe_file_sync
    return transcribe_file_sync


def _transcribe_file(app: Any, **kwargs: Any) -> dict[str, Any]:
    patched_transcriber = _get_transcribe_file_sync()
    if patched_transcriber is not transcribe_file_sync:
        return patched_transcriber(**kwargs)
    service = getattr(app.state, "transcription_service", None)
    if service is not None:
        return service.transcribe_file(**kwargs)
    return transcribe_file_sync(**kwargs)


def _effective_backend(provider: str, model: str) -> str:
    return TranscriptionService.backend(provider, model)


def _effective_asr(
    settings: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    speechmatics_region: str | None = None,
    speechmatics_model: str | None = None,
    speechmatics_diarization: str | None = None,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    return TranscriptionService.resolve_asr(
        settings,
        provider=provider,
        model=model,
        speechmatics_region=speechmatics_region,
        speechmatics_model=speechmatics_model,
        speechmatics_diarization=speechmatics_diarization,
    )


def _normalize_diarization_provider(provider: str | None) -> str:
    selected = str(provider or DIARIZATION_PROVIDER_DISABLED).strip().lower()
    if selected == DIARIZATION_PROVIDER_DISABLED:
        return selected
    if selected not in DIARIZATION_PROVIDERS:
        raise ValueError(f"Unsupported diarization provider: {provider}")
    return selected


def _apply_initial_diarization(
    app: Any,
    audio_path: Path,
    payload: dict[str, Any],
    *,
    provider: str,
    speechmatics_region: str | None,
    speechmatics_model: str | None,
) -> dict[str, Any]:
    if provider == DIARIZATION_PROVIDER_DISABLED:
        return payload
    existing = payload.get("stats", {}).get("speaker_diarization") or {}
    if existing.get("status") == "completed" and existing.get("provider") == provider:
        return payload
    return get_services(app).diarization.process_audio_payload(
        audio_path,
        payload,
        provider=provider,
        speechmatics_region=speechmatics_region,
        speechmatics_model=speechmatics_model,
    )


def run_recording_transcription(
    app: Any,
    recording_id: str,
    body: TranscribeRecordingRequest,
    job: TranscriptionJob | None = None,
) -> dict:
    service: TranscriptionService = get_services(app).transcription
    return service.transcribe_recording(
        app,
        recording_id,
        body,
        job,
        engine=lambda **kwargs: _transcribe_file(app, **kwargs),
    )


def _maybe_start_meeting_pipeline(app: Any, recording_id: str, transcription_id: str | None) -> dict[str, Any] | None:
    settings = load_settings()
    if not settings.get("meeting_auto_analysis"):
        return None
    pipeline_id = settings.get("meeting_default_pipeline") or "meeting_default"
    try:
        return get_services(app).analysis_jobs.create_pipeline(
            AnalysisPipelineRequest(
                recording_id=recording_id,
                transcription_id=transcription_id,
                pipeline_id=pipeline_id,
                source_ids=[item for item in [recording_id, transcription_id] if item],
            )
        )
    except Exception as exc:
        logger.warning("Failed to start meeting analysis pipeline for %s: %s", recording_id, exc)
        return {"status": "failed", "error": str(exc)[:500], "pipeline_id": pipeline_id}


@router.get("/v1/transcription/source-data")
def transcription_source_data(request: Request, limit: int = 100):
    recordings = get_services(request.app).recordings.list(limit=max(1, min(limit, 200)))
    projects = _build_projects(request.app)
    settings = load_settings()
    return {
        "recordings": recordings,
        "recordings_count": len(recordings),
        "projects": projects["items"],
        "settings": {
            "recordings_dir": settings.get("recordings_dir", ""),
            "default_model": settings.get("default_model", ""),
            "default_language": settings.get("default_language", "it"),
            "default_task": settings.get("default_task", "transcribe"),
            "default_word_timestamps": settings.get("default_word_timestamps", False),
            "default_condition_on_previous": settings.get("default_condition_on_previous", False),
            "asr_provider": settings.get("asr_provider", ASR_PROVIDER_LOCAL),
            "speechmatics_region": settings.get("speechmatics_region", ""),
            "speechmatics_model": settings.get("speechmatics_model", ""),
            "speechmatics_diarization": settings.get("speechmatics_diarization", "none"),
            "speechmatics_api_key_configured": bool(
                settings.get("speechmatics_api_key") or get_env_var("SPEECHMATICS_API_KEY")
            ),
            "speaker_diarization_enabled": bool(settings.get("speaker_diarization_enabled")),
            "visual_intelligence_enabled": bool(settings.get("visual_intelligence_enabled")),
        },
    }


@router.post("/v1/audio/transcriptions")
async def transcribe_upload(
    request: Request,
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form("it"),
    task: str = Form("transcribe"),
    response_format: str = Form("json"),
    word_timestamps: str = Form("false"),
    initial_prompt: Optional[str] = Form(None),
    temperature: Optional[float] = Form(None),
    condition_on_previous_text: str = Form("false"),
    verbose: Optional[str] = Form(None),
    stream: str = Form("false"),
    recording_id: Optional[str] = Form(None),
    vad_guided: str = Form(str(VAD_GUIDED_DEFAULT).lower()),
    vad_post_filter: str = Form(str(VAD_POST_FILTER_DEFAULT).lower()),
    asr_provider: Optional[str] = Form(None),
    speechmatics_region: Optional[str] = Form(None),
    speechmatics_model: Optional[str] = Form(None),
    speechmatics_diarization: Optional[str] = Form(None),
    diarization_provider: Optional[str] = Form(None),
):
    started_at = time.perf_counter()
    is_streaming = str_to_bool(stream)
    settings = load_settings()
    provider, provider_model, provider_options, public_options = _effective_asr(
        settings,
        provider=asr_provider,
        model=model or request.app.state.default_model,
        speechmatics_region=speechmatics_region,
        speechmatics_model=speechmatics_model,
        speechmatics_diarization=speechmatics_diarization,
    )
    target_model = provider_model or model or request.app.state.default_model
    selected_diarization_provider = _normalize_diarization_provider(diarization_provider)
    application_request = SingleFileTranscriptionRequest(
        model=target_model,
        language=language,
        task=task,
        word_timestamps=str_to_bool(word_timestamps),
        initial_prompt=initial_prompt,
        temperature=temperature,
        condition_on_previous_text=str_to_bool(condition_on_previous_text, False),
        verbose=None if verbose is None else str_to_bool(verbose),
        vad_guided=str_to_bool(vad_guided, VAD_GUIDED_DEFAULT),
        vad_post_filter=str_to_bool(vad_post_filter, VAD_POST_FILTER_DEFAULT),
        asr_provider=provider,
        provider_options=provider_options,
        public_provider_options=public_options,
        diarization_provider=selected_diarization_provider,
        diarization_region=speechmatics_region,
        diarization_model=speechmatics_model,
    )
    use_case = SingleFileTranscriptionUseCase(get_services(request.app).transcription)

    logger.info(
        "[/v1/audio/transcriptions] Received upload request. File: %r, Size: %s bytes, "
        "Model: %r, Stream: %s",
        file.filename,
        file.size if file.size else "unknown",
        target_model,
        is_streaming,
    )

    suffix = Path(file.filename or "audio").suffix or ".audio"
    try:
        with tempfile_NamedTemporaryFile_patch(suffix=suffix, cleanup=not is_streaming) as tmp_path:
            audio_path = Path(tmp_path)
            audio_path.write_bytes(await file.read())
            logger.info(
                "[/v1/audio/transcriptions] Saved uploaded file to temporary path: %s",
                audio_path,
            )
            cache_key = use_case.cache_key(audio_path, application_request)
            engine = lambda **kwargs: _transcribe_file(request.app, **kwargs)

            if is_streaming and get_cached_result(cache_key) is not None:
                cached_res = use_case.run(
                    request.app,
                    audio_path,
                    application_request,
                    audio_filename=file.filename,
                    recording_id=recording_id,
                    engine=engine,
                    started_at=started_at,
                )

                async def cached_event_generator():
                    try:
                        yield json.dumps({
                            "type": "progress",
                            "step": "loading_model",
                            "message": "Caricamento risultato della trascrizione da cache locale...",
                        }) + "\n"
                        await asyncio.sleep(0.5)
                        yield json.dumps({"type": "completed", "data": cached_res}) + "\n"
                    finally:
                        audio_path.unlink(missing_ok=True)

                return StreamingResponse(
                    cached_event_generator(),
                    media_type="application/x-ndjson",
                )

            if is_streaming:
                if provider != ASR_PROVIDER_LOCAL:
                    async def cloud_event_generator():
                        try:
                            yield json.dumps({
                                "type": "progress",
                                "step": "submitting",
                                "message": "Submitting cloud ASR job...",
                            }) + "\n"
                            payload = await asyncio.to_thread(
                                use_case.run,
                                request.app,
                                audio_path,
                                application_request,
                                audio_filename=file.filename,
                                recording_id=recording_id,
                                engine=engine,
                                started_at=started_at,
                            )
                            yield json.dumps({"type": "completed", "data": payload}) + "\n"
                        except Exception as exc:
                            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
                        finally:
                            audio_path.unlink(missing_ok=True)

                    return StreamingResponse(
                        cloud_event_generator(),
                        media_type="application/x-ndjson",
                    )

                async def event_generator_wrapper():
                    try:
                        async for event in transcribe_stream_generator(
                            audio_path=tmp_path,
                            model=target_model,
                            language=language,
                            task=task,
                            word_timestamps=word_timestamps,
                            initial_prompt=initial_prompt,
                            temperature=temperature,
                            condition_on_previous_text=condition_on_previous_text,
                            cache_key=cache_key,
                            audio_filename=file.filename,
                            recording_id=recording_id,
                            transcription_store=get_services(request.app).transcriptions,
                            started_at=started_at,
                            vad_guided=vad_guided,
                            vad_post_filter=vad_post_filter,
                            asr_provider=provider,
                            backend=_effective_backend(provider, target_model),
                            provider_options=public_options,
                            payload_postprocessor=(
                                lambda source_path, payload: _apply_initial_diarization(
                                    request.app,
                                    source_path,
                                    payload,
                                    provider=selected_diarization_provider,
                                    speechmatics_region=speechmatics_region,
                                    speechmatics_model=speechmatics_model,
                                )
                            ) if selected_diarization_provider != DIARIZATION_PROVIDER_DISABLED else None,
                        ):
                            yield event
                    finally:
                        audio_path.unlink(missing_ok=True)

                return StreamingResponse(
                    event_generator_wrapper(),
                    media_type="application/x-ndjson",
                )

            payload = use_case.run(
                request.app,
                audio_path,
                application_request,
                audio_filename=file.filename,
                recording_id=recording_id,
                engine=engine,
                started_at=started_at,
            )
            if response_format == "text":
                return PlainTextResponse(payload["text"])
            if response_format == "verbose_json":
                return JSONResponse(payload)
            return JSONResponse({"text": payload["text"]})
    except Exception as exc:
        if is_streaming and "tmp_path" in locals():
            Path(tmp_path).unlink(missing_ok=True)
        logger.error(
            "[/v1/audio/transcriptions] Request failed: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {exc}",
        ) from exc


@router.post("/v1/audio/transcriptions/path")
def transcribe_path(request: Request, body: TranscribePathRequest):
    started_at = time.perf_counter()
    settings = load_settings()
    provider, provider_model, provider_options, public_options = _effective_asr(
        settings,
        provider=body.asr_provider,
        model=body.model or request.app.state.default_model,
        speechmatics_region=body.speechmatics_region,
        speechmatics_model=body.speechmatics_model,
        speechmatics_diarization=body.speechmatics_diarization,
    )
    target_model = provider_model or body.model or request.app.state.default_model
    selected_diarization_provider = _normalize_diarization_provider(body.diarization_provider)
    application_request = SingleFileTranscriptionRequest(
        model=target_model,
        language=body.language,
        task=body.task,
        word_timestamps=body.word_timestamps,
        initial_prompt=body.initial_prompt,
        temperature=body.temperature,
        condition_on_previous_text=body.condition_on_previous_text,
        verbose=body.verbose,
        vad_guided=body.vad_guided,
        vad_post_filter=body.vad_post_filter,
        asr_provider=provider,
        provider_options=provider_options,
        public_provider_options=public_options,
        diarization_provider=selected_diarization_provider,
        diarization_region=body.speechmatics_region,
        diarization_model=body.speechmatics_model,
    )
    use_case = SingleFileTranscriptionUseCase(get_services(request.app).transcription)

    audio_path = Path(body.file).expanduser()
    logger.info(
        "[/v1/audio/transcriptions/path] Received request for file: %r, Model: %r",
        str(audio_path),
        target_model,
    )
    if not audio_path.exists():
        logger.error("[/v1/audio/transcriptions/path] File not found: %r", str(audio_path))
        raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

    try:
        payload = use_case.run(
            request.app,
            audio_path,
            application_request,
            audio_filename=audio_path.name,
            recording_id=None,
            engine=lambda **kwargs: _transcribe_file(request.app, **kwargs),
            started_at=started_at,
        )
        elapsed = time.perf_counter() - started_at
        logger.info(
            "[/v1/audio/transcriptions/path] Finished processing. Time taken: %.2f seconds",
            elapsed,
        )
        if body.response_format == "text":
            return PlainTextResponse(payload["text"])
        if body.response_format == "verbose_json":
            return JSONResponse(payload)
        return JSONResponse({"text": payload["text"]})
    except Exception as exc:
        logger.error(
            "[/v1/audio/transcriptions/path] Transcription failed: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {exc}",
        ) from exc


@router.post("/v1/recordings/{recording_id}/transcriptions")
def transcribe_recording(recording_id: str, request: Request, body: TranscribeRecordingRequest):
    try:
        payload = run_recording_transcription(request.app, recording_id, body)
        pipeline = _maybe_start_meeting_pipeline(request.app, recording_id, payload.get("saved_id"))
        if pipeline:
            payload["analysis_pipeline"] = pipeline
        if body.response_format == "text":
            return PlainTextResponse(payload["text"])
        return JSONResponse(payload)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"[/v1/recordings/{recording_id}/transcriptions] Transcription failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        pass


@router.post("/v1/recordings/{recording_id}/transcription-jobs", status_code=202)
def create_transcription_job(recording_id: str, request: Request, body: TranscriptionJobRequest):
    try:
        get_services(request.app).recordings.get(recording_id, include_result=False)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc

    def runner(job: TranscriptionJob) -> dict[str, Any]:
        try:
            payload = run_recording_transcription(request.app, recording_id, body, job)
            pipeline = _maybe_start_meeting_pipeline(request.app, recording_id, payload.get("saved_id"))
            if pipeline:
                payload["analysis_pipeline"] = pipeline
            return payload
        finally:
            pass

    return get_services(request.app).transcription_jobs.create(
        recording_id,
        runner,
        payload={
            "recording_id": recording_id,
            "visual_intelligence_enabled": body.visual_intelligence_enabled,
        },
    )


@router.get("/v1/jobs")
def list_jobs(
    request: Request,
    type: str | None = Query(default=None),
    scope_type: str | None = Query(default=None),
    scope_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    return {
        "items": get_services(request.app).transcription_jobs.list(
            job_type=type,
            scope_type=scope_type,
            scope_id=scope_id,
            limit=limit,
        )
    }


@router.post("/v1/transcriptions/{transcription_id}/diarization-jobs", status_code=202)
def create_diarization_job(
    transcription_id: str,
    request: Request,
    body: DiarizationJobRequest,
):
    try:
        transcription = get_services(request.app).transcriptions.get(transcription_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Transcription not found") from exc
    recording_id = str(transcription.get("recording_id") or "")
    if not recording_id:
        raise HTTPException(
            status_code=400,
            detail="Only transcriptions linked to a recording can be re-diarized",
        )
    try:
        get_services(request.app).recordings.get(recording_id, include_result=False)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc

    def runner(job: TranscriptionJob) -> dict[str, Any]:
        def progress(step: str, value: int, detail: dict[str, Any] | None = None) -> None:
            get_services(request.app).transcription_jobs.update_progress(
                job.id,
                "running",
                value,
                step,
                event_payload=detail,
            )

        return get_services(request.app).diarization.run(
            get_services(request.app).recordings,
            get_services(request.app).transcriptions,
            transcription_id,
            provider=body.provider,
            speechmatics_region=body.speechmatics_region,
            speechmatics_model=body.speechmatics_model,
            progress_callback=progress,
        )

    return get_services(request.app).transcription_jobs.create(
        recording_id,
        runner,
        job_type=DIARIZATION_JOB_TYPE,
        scope_type="transcription",
        scope_id=transcription_id,
        payload={
            "recording_id": recording_id,
            "transcription_id": transcription_id,
            "provider": body.provider,
            "speechmatics_region": body.speechmatics_region,
            "speechmatics_model": body.speechmatics_model,
        },
    )


@router.get("/v1/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    job = get_services(request.app).transcription_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/v1/jobs/{job_id}/events")
def job_events(job_id: str, request: Request):
    if get_services(request.app).transcription_jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")

    def event_stream():
        last_sequence = 0
        while True:
            if hasattr(get_services(request.app).transcription_jobs, "events_after"):
                events = get_services(request.app).transcription_jobs.events_after(job_id, last_sequence) or []
            else:
                events = get_services(request.app).transcription_jobs.drain_events(job_id) or []
            for event in events:
                last_sequence = max(last_sequence, int(event.get("sequence") or last_sequence))
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                    return
            time.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    existing = get_services(request.app).jobs.get(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = (
        get_services(request.app).transcription_jobs.cancel(job_id)
        if existing["type"] in {TRANSCRIPTION_JOB_TYPE, DIARIZATION_JOB_TYPE}
        else get_services(request.app).jobs.request_cancel(job_id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/v1/transcriptions/merge")
def merge_transcriptions(request: Request, body: MergeTranscriptionsRequest):
    try:
        return get_services(request.app).transcriptions.merge(
            transcription_ids=body.transcription_ids,
            title=body.title
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Merge failed: {exc}") from exc


@router.get("/v1/transcriptions")
def list_transcriptions(request: Request, page: int = 1, limit: int = 10):
    items, total = get_services(request.app).transcriptions.list(page=page, limit=limit)
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/v1/transcriptions/{transcription_id}")
def get_transcription(transcription_id: str, request: Request):
    try:
        return get_services(request.app).transcriptions.get(transcription_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Transcription not found")


@router.delete("/v1/transcriptions/{transcription_id}")
def delete_transcription(transcription_id: str, request: Request):
    success = get_services(request.app).transcriptions.delete(transcription_id)
    if not success:
        raise HTTPException(status_code=404, detail="Transcription not found")
    return {"ok": True}


@router.patch("/v1/transcriptions/{transcription_id}/speakers")
def update_transcription_speakers(
    transcription_id: str,
    body: SpeakerNamesRequest,
    request: Request,
):
    try:
        return get_services(request.app).transcriptions.update_speaker_names(
            transcription_id,
            body.names,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v1/transcriptions/{transcription_id}/split")
def split_transcription(transcription_id: str, request: Request):
    try:
        restored_ids = get_services(request.app).transcriptions.split(transcription_id)
        return {"ok": True, "restored_ids": restored_ids}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


import tempfile
import contextlib

@contextlib.contextmanager
def tempfile_NamedTemporaryFile_patch(suffix="", *, cleanup: bool = True):
    """Own a temporary path, optionally transferring cleanup to a stream."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        yield path
    finally:
        if cleanup:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
