from __future__ import annotations

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "interrupted"}

JOB_STATUSES = {
    "queued",
    "running",
    "waiting_for_service",
    "cancel_requested",
    "cancelling",
    "cancelled",
    "interrupted",
    "completed",
    "failed",
    "retrying",
}

# Legacy transcription statuses name the active phase; keep them discoverable.
ACTIVE_JOB_STATUSES = (
    "queued", "running", "waiting_for_service", "retrying", "cancel_requested", "cancelling",
    "validating_audio", "downloading", "loading_model", "transcribing", "transcribing_mic",
    "transcribing_system", "preparing_diarization", "diarizing_system", "diarizing",
    "merging", "visual_processing", "audio_intelligence", "saving", "saving_diarization",
)
