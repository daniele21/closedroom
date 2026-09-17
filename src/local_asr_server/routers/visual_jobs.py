from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from local_asr_server.app_services import get_services
from local_asr_server.recordings import RecordingNotFound
from local_asr_server.transcription_jobs import VISUAL_INTELLIGENCE_JOB_TYPE


router = APIRouter()
_ACTIVE_JOB_STATUSES = {"queued", "running", "waiting_for_service", "retrying", "cancelling"}


@router.post("/v1/recordings/{recording_id}/visual-intelligence-jobs", status_code=202)
def create_visual_intelligence_job(recording_id: str, request: Request):
    services = get_services(request.app)
    try:
        frames = services.recordings.list_visual_frames(recording_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail="Recording not found") from exc
    if not frames:
        raise HTTPException(status_code=409, detail="No screen context was captured for this meeting")

    transcription = services.transcriptions.latest_for_recording(recording_id)
    if transcription is None:
        raise HTTPException(status_code=409, detail="Transcribe the meeting before analyzing screen context")
    transcription_id = str(transcription["id"])

    existing = services.transcription_jobs.list(
        job_type=VISUAL_INTELLIGENCE_JOB_TYPE,
        scope_type="transcription",
        scope_id=transcription_id,
        limit=20,
    )
    if any(job.get("status") in _ACTIVE_JOB_STATUSES for job in existing):
        raise HTTPException(status_code=409, detail="Screen context analysis is already running")

    def run(job):
        current = services.transcriptions.get(transcription_id)
        current["job_id"] = job.id

        def report(progress: dict) -> None:
            total = max(1, int(progress.get("total") or 0))
            processed = max(0, int(progress.get("processed") or 0))
            percent = min(95, 5 + round(90 * min(processed, total) / total))
            services.transcription_jobs.update_progress(
                job.id,
                "running",
                percent,
                "visual_intelligence",
                message="visual_intelligence_progress",
                event_payload=progress,
            )

        updated = services.transcription.visual.process(
            services,
            recording_id,
            current,
            progress_callback=report,
            enabled=True,
            routing_mode="v2",
            cancel_requested=lambda: job.cancel_requested,
        )
        visual = updated.get("stats", {}).get("visual_intelligence") or {}
        status = str(visual.get("status") or "completed")
        if status == "failed":
            raise RuntimeError(str(visual.get("error") or "visual_intelligence_failed"))

        updated.pop("job_id", None)
        persisted = services.transcriptions.replace_visual_intelligence(
            transcription_id,
            updated,
        )
        return {
            "recording_id": recording_id,
            "transcription_id": transcription_id,
            "visual_intelligence": persisted.get("stats", {}).get("visual_intelligence") or visual,
            "outcome_status": "completed_with_warnings" if status == "degraded" else "completed",
        }

    return services.transcription_jobs.create(
        recording_id,
        run,
        job_type=VISUAL_INTELLIGENCE_JOB_TYPE,
        scope_type="transcription",
        scope_id=transcription_id,
        payload={
            "recording_id": recording_id,
            "transcription_id": transcription_id,
            "routing_mode": "v2",
        },
    )


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
