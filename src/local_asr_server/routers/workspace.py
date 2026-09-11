from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request

from local_asr_server.app_services import get_services
from local_asr_server.catalog_search import CatalogMeetingSearch, MeetingSearchUnavailable
from local_asr_server.meeting_diagnostics import build_meeting_diagnostic_report
from local_asr_server.meeting_preparation import MeetingPreparationManager
from local_asr_server.recordings import RecordingConflict, RecordingNotFound
from local_asr_server.routers.helpers import _build_meeting, _build_meetings, _build_projects
from local_asr_server.routers.transcriptions import run_recording_transcription
from local_asr_server.schemas import AnalysisPipelineRequest, TranscriptionJobRequest


router = APIRouter()


@router.get("/v1/projects")
def list_projects(request: Request):
    return _build_projects(request.app)


@router.get("/v1/meetings")
def list_meetings(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None, max_length=512),
    project_name: str | None = Query(default=None, max_length=200),
):
    # Keep the existing recent-meetings response untouched for current consumers.
    # Passing q (including q="") opts into the complete, paged archive projection.
    if q is None and page == 1 and project_name is None:
        return _build_meetings(request.app, limit=limit)

    services = get_services(request.app)
    try:
        result = CatalogMeetingSearch(services.catalog).search(
            query=q or "",
            page=page,
            limit=min(limit, 50),
            project_name=project_name,
        )
    except MeetingSearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    items = []
    for recording_id in result.recording_ids:
        try:
            recording = services.recordings.get(recording_id, include_result=False)
        except RecordingNotFound:
            # Catalog reconciliation is canonical at RecordingStore startup. A missing
            # file here is treated as a stale local artifact rather than expanding the
            # request into an unbounded filesystem recovery scan.
            continue
        items.append(_build_meeting(request.app, recording, compact=True))

    return {
        "items": items,
        "total": result.total,
        "page": result.page,
        "limit": result.limit,
        "has_more": result.has_more,
    }


@router.get("/v1/meetings/{recording_id}")
def get_meeting(recording_id: str, request: Request):
    try:
        recording = get_services(request.app).recordings.get(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Meeting not found") from exc
    return _build_meeting(request.app, recording)


@router.post("/v1/meetings/{recording_id}/prepare", status_code=202)
def prepare_meeting(recording_id: str, request: Request):
    services = get_services(request.app)
    try:
        recording = services.recordings.get(recording_id, include_result=False)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Meeting not found") from exc
    if recording.get("status") in {"recording", "finalizing"}:
        raise HTTPException(status_code=409, detail="Stop the meeting before preparing notes")

    manager = MeetingPreparationManager(
        services,
        default_model=request.app.state.default_model,
    )

    def start_transcription(on_terminal: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        body = TranscriptionJobRequest(visual_intelligence_enabled=False)

        def runner(job):
            return run_recording_transcription(request.app, recording_id, body, job)

        return services.transcription_jobs.create(
            recording_id,
            runner,
            payload={
                "recording_id": recording_id,
                "visual_intelligence_enabled": False,
                "trigger": "meeting_prepare_notes",
            },
            on_terminal=on_terminal,
        )

    def start_pipeline(
        transcription_id: str,
        on_terminal: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        return services.analysis_jobs.create_pipeline(
            AnalysisPipelineRequest(
                recording_id=recording_id,
                transcription_id=transcription_id,
                pipeline_id="meeting_default",
                source_ids=[recording_id, transcription_id],
            ),
            on_terminal=on_terminal,
        )

    try:
        return manager.create(
            recording_id,
            start_transcription=start_transcription,
            start_pipeline=start_pipeline,
        )
    except RecordingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Meeting preparation failed: {exc}") from exc


@router.post("/v1/meetings/{recording_id}/preparation-jobs/{job_id}/cancel")
def cancel_meeting_preparation(recording_id: str, job_id: str, request: Request):
    services = get_services(request.app)
    manager = MeetingPreparationManager(
        services,
        default_model=request.app.state.default_model,
    )
    job = services.jobs.get(job_id)
    if (
        job is None
        or job.get("scope_type") != "recording"
        or job.get("scope_id") != recording_id
    ):
        raise HTTPException(status_code=404, detail="Meeting preparation job not found")
    cancelled = manager.cancel(job_id)
    if cancelled is None:
        raise HTTPException(status_code=404, detail="Meeting preparation job not found")
    return cancelled


@router.get("/v1/meetings/{recording_id}/diagnostics")
def get_meeting_diagnostics(recording_id: str, request: Request):
    try:
        recording = get_services(request.app).recordings.get(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Meeting not found") from exc
    meeting = _build_meeting(request.app, recording)
    configured_log = getattr(request.app.state, "app_log_file", None)
    return build_meeting_diagnostic_report(
        recording_id,
        meeting.get("transcription"),
        get_services(request.app).jobs,
        log_file=Path(configured_log) if configured_log else None,
    )
