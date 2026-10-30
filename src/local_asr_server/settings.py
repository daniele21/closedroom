"""
settings.py — User settings persistence for ClosedRoom.

Settings are stored in ``~/Library/Application Support/ClosedRoom/settings.json``
following the macOS convention for user data.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from local_asr_server.paths import get_settings_file, APP_NAME
from local_asr_server.runtime.models import (
    DEFAULT_LOCAL_LLM_URL,
    DEFAULT_LLM_QUALITY_PRESET,
    DEFAULT_LLM_REASONING,
)
from local_asr_server.asr_provider import (
    ASR_PROVIDER_LOCAL,
    DEFAULT_SPEECHMATICS_DIARIZATION,
    DEFAULT_SPEECHMATICS_MODEL,
    DEFAULT_SPEECHMATICS_REGION,
)


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_VISUAL_FRAME_SIMILARITY_THRESHOLD = 12


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS: dict[str, any] = {
    "transcriptions_dir": str(Path(f"~/ClosedRoom/Transcriptions/{APP_NAME}").expanduser()),
    "recordings_dir": str(Path(f"~/ClosedRoom/Recordings/{APP_NAME}").expanduser()),
    "catalog_db_path": str(Path(f"~/ClosedRoom/closedroom.db").expanduser()),
    # GCS coordinates may be staged, but backup cannot be selected before
    # OAuth, Keychain recovery and canonical RecordingStore integration.
    "storage_mode": "local",
    "gcs_project_id": "",
    "gcs_bucket_name": "",
    "gcs_region": "europe-west8",
    "asr_provider": ASR_PROVIDER_LOCAL,
    "speechmatics_api_key": "",
    "speechmatics_region": DEFAULT_SPEECHMATICS_REGION,
    "speechmatics_model": DEFAULT_SPEECHMATICS_MODEL,
    "speechmatics_diarization": DEFAULT_SPEECHMATICS_DIARIZATION,
    "speechmatics_timeout_seconds": 900,
    "speechmatics_poll_interval_seconds": 5,
    "gemini_api_key": "",
    "gemini_model": DEFAULT_GEMINI_MODEL,
    "llm_provider": "mock",
    "default_model": "",
    "default_language": "it",
    "default_task": "transcribe",
    "default_temperature": 0.0,
    "default_word_timestamps": False,
    "default_condition_on_previous": False,
    "local_llm_mode": "auto",
    "local_llm_client_transport": "legacy",  # developer-preview opt-in: korgis_sdk for Nemotron text only
    "local_llm_url": DEFAULT_LOCAL_LLM_URL,
    "local_llm_model": "nemotron-nano-4b-q8",
    "local_llm_quality_preset": DEFAULT_LLM_QUALITY_PRESET,
    "local_llm_temperature": None,
    "local_llm_reasoning": DEFAULT_LLM_REASONING,
    "local_llm_max_output_tokens": None,
    "local_llm_json_mode": True,
    "local_llm_model_path": "",
    "local_llm_model_paths": {},
    "local_llm_backend": "",
    "local_llm_mmproj_path": "",
    "local_llm_ctx_size": None,
    "local_llm_startup_timeout": None,
    "local_llm_llama_server_bin": "",
    "meeting_auto_analysis": False,
    "meeting_detection_enabled": False,
    "meeting_default_pipeline": "meeting_default",
    "speaker_diarization_enabled": False,
    "speaker_diarization_engine": "fluidaudio-community-1",
    "speaker_diarization_nemotron_preset": "fast128",
    "speaker_diarization_minimum_overlap": 0.25,
    "visual_intelligence_enabled": False,
    "visual_llm_model": "qwen3-vl-4b",
    "visual_routing_mode": "v1",
    "visual_frame_similarity_threshold": DEFAULT_VISUAL_FRAME_SIMILARITY_THRESHOLD,
    "visual_minimum_observations": 3,
    "visual_minimum_margin": 0.2,
    "visual_minimum_distinct_turns": 2,
    "visual_minimum_temporal_support_seconds": 2.0,
}


# ── Public API ────────────────────────────────────────────────────────────────

def load_settings() -> dict[str, any]:
    """
    Load settings from disk, merging with defaults for missing keys.

    Returns a copy of the merged settings dict so callers cannot mutate the
    internal state accidentally.
    """
    settings_file = get_settings_file()
    if not settings_file.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge: defaults first, then on-disk values override
        settings = {**DEFAULT_SETTINGS, **data}
        # Normalize empty string values for fields that must be numbers/None
        for key in (
            "default_temperature",
            "speechmatics_timeout_seconds",
            "speechmatics_poll_interval_seconds",
            "local_llm_temperature",
            "local_llm_max_output_tokens",
            "local_llm_ctx_size",
            "local_llm_startup_timeout",
        ):
            if settings.get(key) == "":
                settings[key] = None
        return settings
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict[str, any]) -> None:
    """
    Persist settings to disk atomically.

    The parent directory is created if it does not exist.
    """
    settings_file = get_settings_file()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{settings_file.name}.", suffix=".tmp", dir=settings_file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, settings_file)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
