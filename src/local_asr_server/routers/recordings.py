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
        return res
    except OSError as exc:
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
    services = get_services(request.app)
    store = services.recordings
    try:
        existing = store.screenshot_for_request(recording_id, body.request_id)
        if existing is not None:
            return _screenshot_payload(recording_id, existing)

        captured = services.capture.capture_screenshot(
            recording_id,
            request_id=body.request_id,
            display_id=body.display_id,
        )
        original = captured.pop("original_bytes")
        thumbnail = captured.pop("thumbnail_bytes")
        saved = store.save_screenshot(
            recording_id,
            request_id=body.request_id,
            capture=captured,
            original=original,
            thumbnail=thumbnail,
        )
        return _screenshot_payload(recording_id, saved)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
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
                if line.strip():
                    candidates.append(json.loads(line))
                    
        observations = []
        obs_path = run_dir / "observations.jsonl"
        if obs_path.exists():
            for line in obs_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    obs = json.loads(line)
                    if task and obs.get("task") != task:
                        continue
                    observations.append(obs)
                    
        total_observations = len(observations)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_obs = observations[start_idx:end_idx]
        
        return {
            "generation_id": generation_id,
            "run_config": run_config,
            "metrics": metrics,
            "result": result,
            "traces": traces,
            "candidates": candidates,
            "observations": paginated_obs,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_observations,
                "has_more": end_idx < total_observations,
            }
        }
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v2/recordings/{recording_id}/visual-runs/{generation_id}/previews/{filename}")
def get_visual_preview(
    recording_id: str,
    generation_id: str,
    filename: str,
    request: Request,
):
    try:
        services = get_services(request.app)
        session_dir = services.recordings.session_dir(recording_id)
        preview_file = (session_dir / "visual-runs" / generation_id / "previews" / filename).resolve()
        if not preview_file.exists():
            raise HTTPException(status_code=404, detail="Preview file not found")
        run_previews_dir = (session_dir / "visual-runs" / generation_id / "previews").resolve()
        if not str(preview_file).startswith(str(run_previews_dir)):
            raise HTTPException(status_code=403, detail="Forbidden")
        return FileResponse(preview_file)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc


@router.post("/v1/recordings/{recording_id}/tracks/{track_id}/chunks")
async def append_recording_track_chunk(
    recording_id: str,
    track_id: str,
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
        res = store.append_track_chunk(
            recording_id,
            track_id,
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


@router.get("/v1/recordings/{recording_id}/tracks/{track_id}/expected-sequence")
def expected_recording_track_sequence(recording_id: str, track_id: str, request: Request):
    try:
        return get_services(request.app).recordings.expected_sequence(recording_id, track_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v1/recordings/{recording_id}/recover")
def recover_recording(recording_id: str, request: Request):
    try:
        return get_services(request.app).recordings.recover(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v1/recordings/{recording_id}/discard", status_code=204)
def discard_recording(recording_id: str, request: Request):
    try:
        get_services(request.app).recordings.discard(recording_id)
        return Response(status_code=204)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v1/recordings/{recording_id}/stop", status_code=202)
def stop_recording(recording_id: str, request: Request):
    store: RecordingStore = get_services(request.app).recordings
    try:
        metadata, _ = store.finalize(recording_id)
        try:
            report = build_quality_report(store.transcribable_tracks(recording_id))
            metadata = store.save_quality_report(recording_id, report)
        except Exception as exc:
            logger.warning("Failed to build recording quality report: %s", exc)
        return metadata
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc


@router.get("/v1/recordings/active")
def get_active_recording(request: Request):
    active = get_services(request.app).recordings.active_recording()
    if not active:
        return {"active": False}
    
    recording_id = active["id"]
    # Check if native capture session is active to fetch volume and real status
    session = get_services(request.app).capture.get_session(recording_id)
    
    mic_db = -120.0
    system_db = -120.0
    warnings = []
    
    if session:
        mic_db = session.last_volume.get("mic", -120.0)
        system_db = session.last_volume.get("system", -120.0)
        warnings = [w.get("message", "") for w in session.warnings]
        
        # Calculate actual bytes written on disk
        bytes_written = 0
        for f_name in ["mic.wav", "system.wav"]:
            p = session.output_dir / f_name
            if p.exists():
                bytes_written += p.stat().st_size
    else:
        bytes_written = active.get("bytes_written", 0)
        
    return {
        "active": True,
        "recording_id": recording_id,
        "title": active.get("title"),
        "capture_backend": active.get("capture_backend"),
        "capture_mode": active.get("capture_mode"),
        "started_at": active.get("created_at"),
        "bytes_written": bytes_written,
        "mic_db": mic_db,
        "system_db": system_db,
        "warnings": warnings,
        "screenshot_count": int(active.get("screenshot_count") or 0),
        "screenshot_display_id": session.screenshot_display_id if session else None,
    }


@router.get("/v1/recordings/{recording_id}")
def get_recording(recording_id: str, request: Request):
    try:
        return get_services(request.app).recordings.get(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc


@router.get("/v1/recordings/{recording_id}/audio")
def get_recording_audio(recording_id: str, request: Request):
    store: RecordingStore = get_services(request.app).recordings
    try:
        metadata = store.get(recording_id, include_result=False)
        return FileResponse(
            store.audio_path(recording_id),
            media_type=metadata["mime_type"],
            filename=Path(metadata["audio_file"]).name,
        )
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/recordings/{recording_id}/intelligence")
def get_recording_intelligence(recording_id: str, request: Request):
    try:
        return get_services(request.app).recordings.get_intelligence(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Audio intelligence not found") from exc


@router.get("/v1/recordings/{recording_id}/tracks/{track_id}/audio")
def get_recording_track_audio(recording_id: str, track_id: str, request: Request):
    store: RecordingStore = get_services(request.app).recordings
    try:
        metadata = store.get(recording_id, include_result=False)
        track = next((item for item in metadata.get("audio_tracks", []) if item.get("id") == track_id), None)
        if track is None:
            raise RecordingConflict("Recording track not found")
        return FileResponse(
            store.track_audio_path(recording_id, track_id),
            media_type=track.get("mime_type") or metadata["mime_type"],
            filename=Path(track.get("audio_file") or f"{track_id}.webm").name,
        )
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/recordings")
def list_recordings(request: Request, limit: int = 20):
    return {"items": get_services(request.app).recordings.list(limit)}


@router.patch("/v1/recordings/{recording_id}")
def update_recording(recording_id: str, request: Request, body: UpdateRecordingRequest):
    store: RecordingStore = get_services(request.app).recordings
    try:
        return store.update(
            recording_id,
            title=body.title,
            project_name=body.project_name,
        )
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc


@router.get("/v1/recordings/{recording_id}/project")
def get_recording_project(recording_id: str, request: Request):
    try:
        recording = get_services(request.app).recordings.get(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    transcription = get_services(request.app).transcriptions.find_for_recording(recording_id)
    return {
        "recording": recording,
        "transcription": transcription,
        "analysis": transcription.get("analysis") if transcription else None,
    }


# get_active_recording moved above get_recording to resolve dynamic path parameter resolution issues


@router.post("/v1/recordings/{recording_id}/control/stop", status_code=202)
def control_stop_recording(recording_id: str, request: Request):
    recording = get_services(request.app).recordings.get(recording_id, include_result=False)
    backend = recording.get("capture_backend", "browser")
    
    # Check if there is an active native session to be absolutely sure
    if get_services(request.app).capture.get_session(recording_id):
        backend = "native"
        
    if backend == "native":
        from local_asr_server.routers.system import stop_capture
        res = stop_capture(recording_id, request)
        return res
    else:
        res = stop_recording(recording_id, request)
        return {"recording": res}


@router.get("/v1/recordings/{recording_id}/overlay/events")
def overlay_events(recording_id: str, request: Request):
    store = get_services(request.app).recordings
    try:
        store.get(recording_id, include_result=False)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc

    def event_stream():
        import json
        import time
        last_sent = None
        while True:
            active = store.active_recording()
            if not active or active.get("id") != recording_id:
                yield f"data: {json.dumps({'active': False})}\n\n"
                return

            session = get_services(request.app).capture.get_session(recording_id)
            
            mic_db = -120.0
            system_db = -120.0
            warnings = []
            
            if session:
                mic_db = session.last_volume.get("mic", -120.0)
                system_db = session.last_volume.get("system", -120.0)
                warnings = [w.get("message", "") for w in session.warnings]
                
                # Check actual bytes written on disk for native capture
                bytes_written = 0
                for f_name in ["mic.wav", "system.wav"]:
                    p = session.output_dir / f_name
                    if p.exists():
                        bytes_written += p.stat().st_size
            else:
                bytes_written = active.get("bytes_written", 0)

            status_payload = {
                "active": True,
                "recording_id": recording_id,
                "title": active.get("title"),
                "capture_backend": active.get("capture_backend"),
                "capture_mode": active.get("capture_mode"),
                "started_at": active.get("created_at"),
                "bytes_written": bytes_written,
                "mic_db": mic_db,
                "system_db": system_db,
                "warnings": warnings,
                "screenshot_count": int(active.get("screenshot_count") or 0),
                "screenshot_display_id": session.screenshot_display_id if session else None,
            }

            if status_payload != last_sent:
                yield f"data: {json.dumps(status_payload)}\n\n"
                last_sent = status_payload

            time.sleep(0.25)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
