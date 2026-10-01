from __future__ import annotations

from typing import Any, Callable

from local_asr_server.transcription_jobs import VISUAL_INTELLIGENCE_JOB_TYPE


_ACTIVE_JOB_STATUSES = {"queued", "running", "waiting_for_service", "retrying", "cancelling"}
TerminalCallback = Callable[[dict[str, Any]], None]


class VisualJobConflict(RuntimeError):
    pass


class VisualEvidenceUnavailable(RuntimeError):
    pass


def start_visual_intelligence_job(
    services: Any,
    recording_id: str,
    *,
    transcription_id: str | None = None,
    on_terminal: TerminalCallback | None = None,
    trigger: str = "visual_analysis",
) -> dict[str, Any]:
    frames = services.recordings.list_visual_evidence_frames(recording_id)
    if not frames:
        raise VisualEvidenceUnavailable("No screen context was captured for this meeting")
    if not any(frame.get("path") is not None for frame in frames):
        raise VisualEvidenceUnavailable("Screen evidence exists but its image assets are unavailable")

    transcription = (
        services.transcriptions.get(transcription_id)
        if transcription_id
        else services.transcriptions.latest_for_recording(recording_id)
    )
    if transcription is None:
        raise VisualEvidenceUnavailable("Transcribe the meeting before analyzing screen context")
    resolved_transcription_id = str(transcription["id"])

    existing = services.transcription_jobs.list(
        job_type=VISUAL_INTELLIGENCE_JOB_TYPE,
        scope_type="transcription",
        scope_id=resolved_transcription_id,
        limit=20,
    )
    if any(job.get("status") in _ACTIVE_JOB_STATUSES for job in existing):
        raise VisualJobConflict("Screen context analysis is already running")

    def run(job):
        current = services.transcriptions.get(resolved_transcription_id)
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
            resolved_transcription_id,
            updated,
        )
        return {
            "recording_id": recording_id,
            "transcription_id": resolved_transcription_id,
            "visual_intelligence": persisted.get("stats", {}).get("visual_intelligence") or visual,
            "outcome_status": "completed_with_warnings" if status == "degraded" else "completed",
        }

    return services.transcription_jobs.create(
        recording_id,
        run,
        job_type=VISUAL_INTELLIGENCE_JOB_TYPE,
        scope_type="transcription",
        scope_id=resolved_transcription_id,
        payload={
            "recording_id": recording_id,
            "transcription_id": resolved_transcription_id,
            "routing_mode": "v2",
            "trigger": trigger,
        },
        on_terminal=on_terminal,
    )
