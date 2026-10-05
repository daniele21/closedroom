from __future__ import annotations

from local_asr_server.app_services import get_services

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from local_asr_server.audio_diagnostics import build_quality_report
from local_asr_server.recordings import (
    RecordingConflict,
    RecordingNotFound,
    RecordingStore,
)
from local_asr_server.schemas import CreateRecordingRequest, ScreenshotCaptureRequest, UpdateRecordingRequest

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.post("/v1/recordings", status_code=201)
def create_recording(request: Request, body: CreateRecordingRequest):
    store: RecordingStore = get_services(request.app).recordings
    try:
        res = store.create(
            title=body.title,
            project_name=body.project_name,
            mime_type=body.mime_type,
            model=body.model or request.app.state.default_model,
            language=body.language,
            capture_mode=body.capture_mode or "legacy_mixed",
            capture_backend=body.capture_backend or "browser",
        )
        logger.info(
            "Created recording session %s (title=%r, backend=%s, mode=%s)",
            res.get("id"), body.title, body.capture_backend, body.capture_mode,
        )
        return res
    except OSError as exc:
        logger.error("Failed to create recording session: %s", exc)
        raise HTTPException(status_code=507, detail=str(exc)) from exc


@router.post("/v1/recordings/{recording_id}/chunks")
async def append_recording_chunk(
    recording_id: str,
    request: Request,
    file: UploadFile = File(...),
    sequence: int = Form(...),
    sha256: Optional[str] = Form(None),
    size: Optional[int] = Form(None),
    client_started_at_ms: Optional[float] = Form(None),
    client_chunk_start_ms: Optional[float] = Form(None),
    client_chunk_end_ms: Optional[float] = Form(None),
):
    store: RecordingStore = get_services(request.app).recordings
    try:
        content = await file.read()
        res = store.append_chunk(
            recording_id,
            sequence,
            content,
            sha256=sha256,
            size=size,
            client_started_at_ms=client_started_at_ms,
            client_chunk_start_ms=client_chunk_start_ms,
            client_chunk_end_ms=client_chunk_end_ms,
        )
        
        return res
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc




def _screenshot_payload(recording_id: str, item: dict) -> dict:
    screenshot_id = item["screenshot_id"]
    return {
        **item,
        "original_url": f"/v1/recordings/{recording_id}/screenshots/{screenshot_id}/original",
        "thumbnail_url": f"/v1/recordings/{recording_id}/screenshots/{screenshot_id}/thumbnail",
    }


@router.get("/v1/recordings/{recording_id}/screenshots")
def list_screenshots(recording_id: str, request: Request):
    try:
        items = get_services(request.app).recordings.list_screenshots(recording_id)
        return {
            "items": [_screenshot_payload(recording_id, item) for item in items],
            "total": len(items),
        }
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v1/recordings/{recording_id}/screenshots", status_code=201)
def capture_screenshot(recording_id: str, request: Request, body: ScreenshotCaptureRequest):
    logger.info(
        "Screenshot requested for recording=%s: request_id=%s, display_id=%s",
        recording_id, body.request_id, body.display_id,
    )
    services = get_services(request.app)
    store = services.recordings
    try:
        existing = store.screenshot_for_request(recording_id, body.request_id)
        if existing is not None:
            logger.info("Returning existing screenshot for request_id=%s", body.request_id)
            return _screenshot_payload(recording_id, existing)

        services.capture.begin_screenshot(recording_id)
        staging = None
        try:
            staging = store.reserve_screenshot_capture(
                recording_id,
                request_id=body.request_id,
            )
            if staging.get("existing") is not None:
                return _screenshot_payload(recording_id, staging["existing"])
            captured = services.capture.capture_screenshot(
                recording_id,
                request_id=body.request_id,
                display_id=body.display_id,
                admission_held=True,
                original_path=staging["original_path"],
                thumbnail_path=staging["thumbnail_path"],
            )
            saved = store.commit_screenshot_capture(
                recording_id,
                request_id=body.request_id,
                token=staging["token"],
                capture=captured,
            )
            logger.info(
                "Screenshot successfully saved: recording=%s, id=%s, seq=%s, timestamp=%.2fs "
                "roundtrip_ms=%s persist_ms=%s",
                recording_id,
                saved.get("id"),
                saved.get("sequence"),
                saved.get("timestamp", 0),
                saved.get("roundtrip_ms"),
                saved.get("persist_ms"),
            )
            return _screenshot_payload(recording_id, saved)
        finally:
            if staging is not None:
                store.discard_screenshot_capture(recording_id, staging.get("token"))
            services.capture.finish_screenshot(recording_id)
    except RecordingNotFound as exc:
        logger.error("Screenshot failed: Recording %s not found", recording_id)
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except ValueError as exc:
        logger.error("Screenshot failed (ValueError) for recording %s: %s", recording_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecordingConflict as exc:
        logger.error("Screenshot failed (RecordingConflict) for recording %s: %s", recording_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("Screenshot failed (RuntimeError) for recording %s: %s", recording_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Screenshot failed (OSError) for recording %s: %s", recording_id, exc)
        raise HTTPException(status_code=507, detail=str(exc)) from exc


@router.get("/v1/recordings/{recording_id}/screenshots/{screenshot_id}/original")
def get_screenshot_original(recording_id: str, screenshot_id: str, request: Request):
    try:
        path = get_services(request.app).recordings.screenshot_asset_path(
            recording_id, screenshot_id, thumbnail=False,
        )
        return FileResponse(path, media_type="image/jpeg")
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Screenshot not found") from exc


@router.get("/v1/recordings/{recording_id}/screenshots/{screenshot_id}/thumbnail")
def get_screenshot_thumbnail(recording_id: str, screenshot_id: str, request: Request):
    try:
        path = get_services(request.app).recordings.screenshot_asset_path(
            recording_id, screenshot_id, thumbnail=True,
        )
        return FileResponse(path, media_type="image/jpeg")
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Screenshot not found") from exc


@router.delete("/v1/recordings/{recording_id}/screenshots/{screenshot_id}", status_code=204)
def delete_screenshot(recording_id: str, screenshot_id: str, request: Request):
    try:
        get_services(request.app).recordings.delete_screenshot(recording_id, screenshot_id)
        return Response(status_code=204)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Screenshot not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/v1/recordings/{recording_id}/visual-frames", status_code=202)
async def append_visual_frame(
    recording_id: str,
    request: Request,
    file: UploadFile = File(...),
    sequence: int = Form(...),
    timestamp: float = Form(...),
):
    try:
        return get_services(request.app).recordings.stage_visual_frame(
            recording_id, sequence, timestamp, await file.read()
        )
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/recordings/{recording_id}/visual-frames")
def list_visual_frames(recording_id: str, request: Request):
    try:
        frames = get_services(request.app).recordings.list_visual_frames(recording_id)
        return {
            "items": [
                {
                    "sequence": int(frame["sequence"]),
                    "timestamp": float(frame["timestamp"]),
                    "url": f"/v1/recordings/{recording_id}/visual-frames/{int(frame['sequence'])}",
                }
                for frame in frames
            ],
            "total": len(frames),
        }
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc


@router.get("/v1/recordings/{recording_id}/visual-frames/{sequence}")
def get_visual_frame(recording_id: str, sequence: int, request: Request):
    try:
        frames = get_services(request.app).recordings.list_visual_frames(recording_id)
        frame = next((item for item in frames if int(item["sequence"]) == sequence), None)
        if frame is None:
            raise HTTPException(status_code=404, detail="Visual frame not found")
        return FileResponse(Path(frame["path"]), media_type="image/jpeg")
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc


@router.get("/v1/recordings/{recording_id}/visual-intelligence")
def get_visual_intelligence(recording_id: str, request: Request):
    try:
        return get_services(request.app).recordings.get_visual_intelligence(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v2/recordings/{recording_id}/visual-intelligence")
def get_visual_intelligence_v2(recording_id: str, request: Request):
    try:
        return get_services(request.app).recordings.get_visual_intelligence_v2(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v2/recordings/{recording_id}/visual-debug")
def get_visual_debug(
    recording_id: str,
    request: Request,
    page: int = 1,
    limit: int = 50,
    task: Optional[str] = None,
):
    import json
    try:
        services = get_services(request.app)
        session_dir = services.recordings.session_dir(recording_id)
        current_path = session_dir / "current_visual_generation.json"
        if not current_path.exists():
            runs_dir = session_dir / "visual-runs"
            if not runs_dir.exists():
                raise HTTPException(status_code=404, detail="No visual runs found")
            runs = sorted(runs_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not runs:
                raise HTTPException(status_code=404, detail="No visual runs found")
            generation_id = runs[0].name
        else:
            current = json.loads(current_path.read_text(encoding="utf-8"))
            generation_id = current["generation_id"]
            
        run_dir = session_dir / "visual-runs" / generation_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="Run files not found")
            
        run_config = {}
        config_path = run_dir / "run.json"
        if config_path.exists():
            run_config = json.loads(config_path.read_text(encoding="utf-8"))
            
        metrics = {}
        metrics_path = run_dir / "metrics.json"
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            
        result = {}
        result_path = run_dir / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            
        traces = []
        trace_path = run_dir / "trace.jsonl"
        if trace_path.exists():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    traces.append(json.loads(line))
                    
        candidates = []
        routing_path = run_dir / "routing.jsonl"
        if routing_path.exists():
            for line in routing_path.read_text(encoding="utf-8").splitlines():