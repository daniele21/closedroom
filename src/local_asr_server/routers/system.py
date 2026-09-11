from __future__ import annotations

from local_asr_server.app_services import get_services

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from local_asr_server.audio_router import AudioRouter
from local_asr_server.app_identity import get_app_identity
from local_asr_server.settings import load_settings
from local_asr_server.prompts import load_prompts, save_prompts
from local_asr_server.recordings import RecordingConflict, RecordingNotFound
from local_asr_server.schemas import (
    OverlayRequest,
    OverlayResizeRequest,
    CaptureEnsurePermissionsRequest,
    CaptureStartRequest,
)
from local_asr_server.asr_provider import asr_catalog
from local_asr_server.macos_permissions import accessibility_status
from local_asr_server.runtime.resource_metrics import ResourceMetricsCollector

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    active_recording = get_services(request.app).recordings.active_recording()
    active_jobs = get_services(request.app).jobs.list_jobs(limit=100)
    transcribing = any(
        job["type"] == "transcription" and job["status"] not in {"completed", "failed", "cancelled", "interrupted"}
        for job in active_jobs
    )
    status_str = "recording" if active_recording else ("transcribing" if transcribing else "idle")
    return {
        "ok": True,
        "server": "local-asr-server",
        **get_app_identity().as_health_payload(),
        "backend": "mlx-whisper",
        "default_model": request.app.state.default_model,
        "status": status_str,
        "endpoints": [
            "POST /v1/audio/transcriptions",
            "POST /v1/audio/transcriptions/path",
            "GET /v1/asr/providers",
            "POST /v1/recordings",
            "POST /v1/recordings/{id}/chunks",
            "POST /v1/recordings/{id}/tracks/{track_id}/chunks",
            "GET /v1/recordings/{id}/tracks/{track_id}/expected-sequence",
            "POST /v1/recordings/{id}/stop",
            "POST /v1/recordings/{id}/recover",
            "POST /v1/recordings/{id}/discard",
            "GET /v1/capture/capabilities",
            "GET /v1/capture/permissions",
            "POST /v1/capture/request-permissions",
            "POST /v1/capture/ensure-permissions",
            "GET /v1/capture/diagnostics",
            "GET /v1/system/accessibility",
            "POST /v1/recordings/{id}/capture/start",
            "GET /v1/recordings/{id}/capture/events",
            "POST /v1/recordings/{id}/capture/stop",
            "POST /v1/recordings/{id}/capture/cancel",
            "POST /v1/recordings/{id}/transcription-jobs",
            "POST /v1/analysis-jobs",
            "POST /v1/analysis-pipelines",
            "GET /v1/analysis/templates",
            "GET /v1/analysis/pipelines",
            "GET /v1/jobs/{job_id}",
            "GET /v1/analysis-runs/{analysis_run_id}",
            "GET /v1/analysis-runs",
            "GET /v1/meetings",
            "GET /v1/meetings/{recording_id}",
            "GET /v1/recordings/{id}",
            "GET /v1/recordings/{id}/audio",
            "GET /v1/recordings/{id}/project",
            "GET /v1/projects",
            "GET /v1/runtime/status",
            "GET /v1/runtime/resources",
            "GET /v1/runtime/services",
            "GET /v1/runtime/services/llm",
            "POST /v1/runtime/services/llm/start",
            "POST /v1/runtime/services/llm/stop",
            "POST /v1/runtime/services/llm/restart",
            "GET /v1/runtime/services/llm/logs",
            "GET /v1/system/audio/status",
            "POST /v1/system/audio/activate",
            "POST /v1/system/audio/restore",
            "GET /health",
        ],
        "recordings": True,
    }


@router.get("/v1/session")
def session(request: Request, response: Response) -> dict:
    if request.app.state.auth_enabled:
        response.set_cookie(
            "closedroom_session",
            request.app.state.api_token,
            httponly=True,
            secure=False,
            samesite="strict",
            max_age=60 * 60 * 24,
        )
    return {
        "auth_enabled": request.app.state.auth_enabled,
        "token": request.app.state.api_token if request.app.state.auth_enabled else None,
    }


@router.get("/v1/system/audio/status")
def audio_status():
    return AudioRouter.get_status()


@router.post("/v1/system/audio/activate")
def activate_audio_route():
    success = AudioRouter.route_to_multi_output()
    status = AudioRouter.get_status()
    return {
        **status,
        "success": success,
        "routing_active": success,
    }


@router.post("/v1/system/audio/restore")
def restore_audio_route():
    success = AudioRouter.restore_original_output()
    return {
        **AudioRouter.get_status(),
        "success": success,
        "routing_active": False,
    }


@router.post("/v1/system/audio-route/test-route")
def test_audio_route():
    return activate_audio_route()


@router.post("/v1/system/audio-route/test-restore")
def test_audio_restore():
    return restore_audio_route()


@router.get("/v1/capture/capabilities")
def capture_capabilities(request: Request):
    native = get_services(request.app).capture.capabilities()
    return {
        "default_backend": "native" if native.get("available") else "browser",
        "native": native,
        "fallbacks": ["browser_blackhole"],
    }


@router.get("/v1/capture/permissions")
def capture_permissions(request: Request):
    return get_services(request.app).capture.permissions()


@router.post("/v1/capture/request-permissions")
def request_capture_permissions(request: Request):
    return get_services(request.app).capture.request_permissions()


@router.post("/v1/capture/ensure-permissions")
def ensure_capture_permissions(request: Request, body: CaptureEnsurePermissionsRequest):
    try:
        return get_services(request.app).capture.ensure_permissions(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/capture/diagnostics")
def capture_diagnostics(request: Request):
    return get_services(request.app).capture.diagnostics()


@router.get("/v1/system/accessibility")
def system_accessibility():
    return accessibility_status()


@router.get("/v1/capture/windows")
def capture_windows(request: Request):
    return get_services(request.app).capture.windows()


@router.post("/v1/recordings/{recording_id}/capture/start", status_code=202)
def start_capture(recording_id: str, request: Request, body: CaptureStartRequest):
    store = get_services(request.app).recordings
    try:
        session_dir = store.session_dir(recording_id)
        if body.visual_window_id is not None and not 0.1 <= body.visual_fps <= 2.0:
            raise ValueError("visual_fps must be between 0.1 and 2.0")
        result = get_services(request.app).capture.start(
            recording_id, session_dir, body.mode,
            visual_window_id=body.visual_window_id, visual_fps=body.visual_fps,
        )
        store.mark_capture_started(recording_id, backend="native")
        return result
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except (RuntimeError, ValueError, RecordingConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/recordings/{recording_id}/capture/events")
def capture_events(recording_id: str, request: Request):
    store = get_services(request.app).recordings
    try:
        store.get(recording_id, include_result=False)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc

    def event_stream():
        while True:
            events = get_services(request.app).capture.drain_events(recording_id)
            for event in events:
                try:
                    store.mark_capture_event(recording_id, event)
                except Exception:
                    logger.warning("Failed to persist capture event", exc_info=True)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in {"stopped", "error"}:
                    return
            time.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/recordings/{recording_id}/capture/stop", status_code=202)
def stop_capture(recording_id: str, request: Request):
    store = get_services(request.app).recordings
    try:
        result = get_services(request.app).capture.stop(recording_id)
        for event in result.get("events", []):
            try:
                store.mark_capture_event(recording_id, event)
            except Exception:
                logger.warning("Failed to persist capture event", exc_info=True)
        from local_asr_server.audio_diagnostics import build_quality_report
        metadata, _ = store.finalize(recording_id)
        try:
            report = build_quality_report(store.transcribable_tracks(recording_id))
            metadata = store.save_quality_report(recording_id, report)
        except Exception as exc:
            logger.warning("Failed to build recording quality report: %s", exc)
        return {"capture": result, "recording": metadata}
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v1/recordings/{recording_id}/capture/cancel", status_code=202)
def cancel_capture(recording_id: str, request: Request):
    try:
        result = get_services(request.app).capture.cancel(recording_id)
        get_services(request.app).recordings.discard(recording_id)
        return result
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/models/check-cache")
def check_model_cache(request: Request, model: Optional[str] = None):
    from local_asr_server.transcriber import is_model_cached
    target = model if model else request.app.state.default_model
    return {"model": target, "cached": is_model_cached(target)}


@router.get("/v1/asr/providers")
def get_asr_providers(request: Request):
    settings = load_settings()
    return asr_catalog(settings, getattr(request.app.state, "default_model", ""))


@router.get("/v1/prompts")
def get_prompts(request: Request):
    return load_prompts(getattr(request.app.state, "prompts_file", None))


@router.post("/v1/prompts")
def update_prompts(request: Request, body: dict[str, dict[str, str]]):
    try:
        save_prompts(body, getattr(request.app.state, "prompts_file", None))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nel salvataggio dei prompt: {e}")


@router.get("/v1/stats")
def get_stats(request: Request):
    stats = get_services(request.app).catalog.stats()
    if stats["latest_recording"] is None:
        recordings = get_services(request.app).recordings.list(limit=1)
        stats["latest_recording"] = recordings[0] if recordings else None
    return stats


@router.get("/v1/runtime/resources")
def runtime_resources(request: Request):
    runtime = get_services(request.app).runtime
    llm = runtime.llm_status()
    arbiter = getattr(request.app.state, "heavy_workload_arbiter", None)
    return ResourceMetricsCollector().snapshot(
        sidecar_pid=llm.get("pid"),
        workload_arbiter=arbiter,
    )


@router.get("/v1/runtime/status")
def runtime_status(request: Request):
    return {
        **get_services(request.app).runtime.status(),
        "resources": runtime_resources(request),
    }


@router.get("/v1/runtime/services")
def runtime_services(request: Request):
    return get_services(request.app).runtime.status()


@router.get("/v1/runtime/services/llm")
def llm_runtime_status(request: Request):
    return get_services(request.app).runtime.llm_status()


@router.post("/v1/runtime/services/llm/start", status_code=202)
def start_llm_runtime_service(request: Request):
    return get_services(request.app).runtime.start_llm()


@router.post("/v1/runtime/services/llm/stop")
def stop_llm_runtime_service(request: Request):
    return get_services(request.app).runtime.stop_llm()


@router.post("/v1/runtime/services/llm/restart", status_code=202)
def restart_llm_runtime_service(request: Request):
    return get_services(request.app).runtime.restart_llm()


@router.get("/v1/runtime/services/llm/logs")
def llm_runtime_logs(request: Request, tail: int = Query(default=200, ge=1, le=2000)):
    return get_services(request.app).runtime.llm_logs(tail)


@router.post("/v1/system/window/overlay")
def toggle_overlay_window(request: Request, body: OverlayRequest):
    window_manager = getattr(request.app.state, "window_manager", None)
    if not window_manager:
        return {"success": False, "error": "Native window manager not available"}
        
    from local_asr_server.window import run_on_main_thread
    
    if body.show:
        run_on_main_thread(window_manager.show_overlay)
    else:
        run_on_main_thread(window_manager.hide_overlay)
        
    return {"success": True}


@router.post("/v1/system/window/overlay/resize")
def resize_overlay_window(request: Request, body: OverlayResizeRequest):
    window_manager = getattr(request.app.state, "window_manager", None)
    if not window_manager:
        return {"success": False, "error": "Native window manager not available"}
        
    from local_asr_server.window import run_on_main_thread
    run_on_main_thread(lambda: window_manager.set_overlay_size(body.width, body.height))
    return {"success": True}


@router.post("/v1/system/select-directory")
def select_directory():
    import subprocess
    try:
        script = 'tell application "System Events" to set frontmost of process "Finder" to true\n' \
                 'POSIX path of (choose folder with prompt "Seleziona la cartella di destinazione:")'
        cmd = ["osascript", "-e", script]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            path = result.stdout.strip()
            return {"path": path}
        else:
            return {"path": None, "error": "Selezione annullata o fallita."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nell'apertura della dialog: {e}")


@router.post("/v1/system/select-file")
def select_file():
    import subprocess
    try:
        # Prompt user to choose a .gguf file
        script = 'tell application "System Events" to set frontmost of process "Finder" to true\n' \
                 'POSIX path of (choose file of type {"gguf"} with prompt "Seleziona il modello GGUF:")'
        cmd = ["osascript", "-e", script]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            path = result.stdout.strip()
            return {"path": path}
        else:
            return {"path": None, "error": "Selezione annullata o fallita."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nell'apertura della dialog: {e}")
