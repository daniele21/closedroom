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

from local_asr_server.paths import get_settings_file, get_app_support_dir, is_development_profile, APP_NAME
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
    # Safe local audio-retention preference only. GCS upload/hydration and
    # automatic eviction are NOT integrated or enabled at this stage.
    "audio_local_retention_days": 14,
    "audio_auto_cleanup_enabled": False,
    "meeting_auto_analysis": False,
    "meeting_detection_enabled": True,  # Content-free local app-activity observation; recording stays manual.
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


def _profile_defaults() -> dict[str, any]:
    defaults = DEFAULT_SETTINGS.copy()
    if is_development_profile():
        root = get_app_support_dir() / "Data"
        defaults.update({
            "recordings_dir": str(root / "Recordings"),
            "transcriptions_dir": str(root / "Transcriptions"),
            "catalog_db_path": str(root / "closedroom.db"),
        })
    return defaults


def validate_development_storage(
    settings: dict[str, any],
    *,
    recordings_dir: Path | str | None = None,
    catalog_db: Path | str | None = None,
) -> None:
    """Fail closed if source-mode writable state escapes its own profile.

    This also rejects symlinks that resolve into production. Only the explicit
    source-run profile is confined; installed app paths remain unchanged.
    """
    if not is_development_profile():
        return
    root = (get_app_support_dir() / "Data").resolve()
    paths = {
        "recordings_dir": recordings_dir or settings.get("recordings_dir"),
        "transcriptions_dir": settings.get("transcriptions_dir"),
        "catalog_db_path": catalog_db or settings.get("catalog_db_path"),
    }
    normalized: dict[str, Path] = {}
    for key, raw in paths.items():
        if not raw:
            raise ValueError(f"Development profile is missing {key}")
        candidate = Path(raw).expanduser().resolve()
        if root not in candidate.parents:
            raise ValueError(
                f"Development profile {key} must be inside {root}; "
                "the installed app's data cannot be shared with source mode."
            )
        normalized[key] = candidate
    if normalized["recordings_dir"] == normalized["transcriptions_dir"]:
        raise ValueError("Development recordings and transcriptions directories must differ")
    if normalized["catalog_db_path"] in (
        normalized["recordings_dir"], normalized["transcriptions_dir"],
    ):
        raise ValueError("Development catalog must be a file, not a media directory")


# ── Public API ────────────────────────────────────────────────────────────────

def load_settings() -> dict[str, any]:
    """
    Load settings from disk, merging with defaults for missing keys.

    Returns a copy of the merged settings dict so callers cannot mutate the
    internal state accidentally.
    """
    settings_file = get_settings_file()
    defaults = _profile_defaults()
    if not settings_file.exists():
        validate_development_storage(defaults)
        return defaults
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Settings must contain an object")
    except (OSError, ValueError, TypeError):
        data = {}
    settings = {**defaults, **data}
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
    validate_development_storage(settings)
    return settings


def save_settings(settings: dict[str, any]) -> None:
    """
    Persist settings to disk atomically.

    The parent directory is created if it does not exist.
    """
    validate_development_storage({**_profile_defaults(), **settings})
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
