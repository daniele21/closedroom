from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from local_asr_server.app_services import get_services
from local_asr_server.recordings import RecordingNotFound
from local_asr_server.transcription_jobs import VISUAL_INTELLIGENCE_JOB_TYPE
from local_asr_server.visual_intelligence.jobs import (
    VisualEvidenceUnavailable,
    VisualJobConflict,
    start_visual_intelligence_job,
)


router = APIRouter()


@router.post("/v1/recordings/{recording_id}/visual-intelligence-jobs", status_code=202)
def create_visual_intelligence_job(recording_id: str, request: Request):
    services = get_services(request.app)
    try:
        return start_visual_intelligence_job(
            services,
            recording_id,
            trigger="manual_visual_analysis",
        )
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    except VisualJobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except VisualEvidenceUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v1/visual-intelligence-jobs/{job_id}/cancel")
def cancel_visual_intelligence_job(job_id: str, request: Request):
    services = get_services(request.app)
    job = services.transcription_jobs.get(job_id)
    if job is None or job.get("type") != VISUAL_INTELLIGENCE_JOB_TYPE:
        raise HTTPException(status_code=404, detail="Visual intelligence job not found")
    cancelled = services.transcription_jobs.cancel(job_id)
    if cancelled is None:
        raise HTTPException(status_code=404, detail="Visual intelligence job not found")
    return cancelled
