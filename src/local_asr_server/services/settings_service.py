from __future__ import annotations

from pathlib import Path
import math
from typing import Any

from local_asr_server.asr_provider import normalize_asr_provider, speechmatics_options_from_settings
from local_asr_server.env import get_env_var
from local_asr_server.schemas import SettingsRequest
from local_asr_server.settings import DEFAULT_SETTINGS, load_settings, save_settings
from local_asr_server.speaker_diarization import DIARIZATION_ENGINES, NEMOTRON3_PRESETS
from local_asr_server.analysis_templates import PIPELINES
from local_asr_server.llm import LLM_PROVIDER_NAMES
from local_asr_server.runtime.models import (
    LLM_QUALITY_PRESETS,
    LLM_REASONING_POLICIES,
    LOCAL_LLM_MODES,
)


PRIVATE_SETTING_KEYS = frozenset({"gemini_api_key", "speechmatics_api_key"})
EXPLICITLY_NULLABLE_SETTING_KEYS = frozenset(
    {
        "default_temperature",
        "speechmatics_timeout_seconds",
        "speechmatics_poll_interval_seconds",
        "local_llm_temperature",
        "local_llm_max_output_tokens",
        "local_llm_ctx_size",
        "local_llm_startup_timeout",
    }
)
DIRECTORY_SETTING_LABELS = {
    "transcriptions_dir": "Directory trascrizioni",
    "recordings_dir": "Directory audio",
}


class InvalidSettings(ValueError):
    """Raised when a settings patch cannot be normalized or validated."""


class SettingsService:
    """Own loading, partial updates, validation, and public serialization."""

    def get_public(self) -> dict[str, Any]:
        settings = load_settings()
        public_settings = {
            key: value for key, value in settings.items() if key not in PRIVATE_SETTING_KEYS
        }
        return {
            **public_settings,
            "gemini_api_key_configured": bool(
                settings.get("gemini_api_key") or get_env_var("GEMINI_API_KEY")
            ),
            "speechmatics_api_key_configured": bool(
                settings.get("speechmatics_api_key") or get_env_var("SPEECHMATICS_API_KEY")
            ),
        }

    def update(self, body: SettingsRequest) -> dict[str, Any]:
        current = load_settings()
        patch = self._request_patch(body)

        for key, value in patch.items():
            if key in DIRECTORY_SETTING_LABELS:
                if value:
                    current[key] = self._writable_directory(
                        value, label=DIRECTORY_SETTING_LABELS[key]
                    )
                continue
            if key == "asr_provider" and value is not None:
                try:
                    current[key] = normalize_asr_provider(value)
                except ValueError as exc:
                    raise InvalidSettings(str(exc)) from exc
                continue
            if value is not None or key in EXPLICITLY_NULLABLE_SETTING_KEYS:
                current[key] = value

        try:
            speechmatics_options_from_settings(current)
        except ValueError as exc:
            raise InvalidSettings(str(exc)) from exc
        self._validate_choices(current)

        save_settings(current)
        return self.get_public()

    @staticmethod
    def _request_patch(body: SettingsRequest) -> dict[str, Any]:
        if hasattr(body, "model_dump"):
            patch = body.model_dump(exclude_unset=True)
        else:
            patch = body.dict(exclude_unset=True)
        return {key: value for key, value in patch.items() if key in DEFAULT_SETTINGS}

    @staticmethod
    def _writable_directory(value: str, *, label: str) -> str:
        path = Path(value).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            test_file.touch()
            test_file.unlink()
        except Exception as exc:
            raise InvalidSettings(f"{label} non valida o non scrivibile: {exc}") from exc
        return str(path)

    @staticmethod
    def _validate_choices(settings: dict[str, Any]) -> None:
        choices = {
            "llm_provider": LLM_PROVIDER_NAMES,
            "local_llm_mode": LOCAL_LLM_MODES,
            "local_llm_quality_preset": LLM_QUALITY_PRESETS,
            "local_llm_reasoning": LLM_REASONING_POLICIES,
            "meeting_default_pipeline": frozenset(PIPELINES),
            "speaker_diarization_engine": DIARIZATION_ENGINES,
            "speaker_diarization_nemotron_preset": NEMOTRON3_PRESETS,
            "default_task": frozenset({"transcribe", "translate"}),
            "visual_routing_mode": frozenset({"v1", "shadow", "v2"}),
        }
        for key, allowed in choices.items():
            value = settings.get(key)
            if value not in allowed:
                raise InvalidSettings(f"Unsupported {key}: {value}")

        for key in ("speechmatics_timeout_seconds", "speechmatics_poll_interval_seconds"):
            value = settings.get(key)
            if value is not None and value <= 0:
                raise InvalidSettings(f"{key} must be greater than zero")

        minimum_observations = settings.get("visual_minimum_observations")
        if not isinstance(minimum_observations, int) or minimum_observations < 1:
            raise InvalidSettings("visual_minimum_observations must be a positive integer")
        minimum_margin = settings.get("visual_minimum_margin")
        if not isinstance(minimum_margin, (int, float)) or not 0 <= float(minimum_margin) <= 1:
            raise InvalidSettings("visual_minimum_margin must be between zero and one")
        minimum_turns = settings.get("visual_minimum_distinct_turns")
        if not isinstance(minimum_turns, int) or minimum_turns < 1:
            raise InvalidSettings("visual_minimum_distinct_turns must be a positive integer")
        temporal_support = settings.get("visual_minimum_temporal_support_seconds")
        if not isinstance(temporal_support, (int, float)) or float(temporal_support) < 0:
            raise InvalidSettings("visual_minimum_temporal_support_seconds must be non-negative")
        similarity_threshold = settings.get("visual_frame_similarity_threshold")
        if (
            not isinstance(similarity_threshold, int)
            or isinstance(similarity_threshold, bool)
            or not 0 <= similarity_threshold <= 64
        ):
            raise InvalidSettings(
                "visual_frame_similarity_threshold must be an integer between zero and 64"
            )
        diarization_overlap = settings.get("speaker_diarization_minimum_overlap")
        if not isinstance(diarization_overlap, (int, float)) or not 0 <= float(diarization_overlap) <= 1:
            raise InvalidSettings("speaker_diarization_minimum_overlap must be between zero and one")

        temperature = settings.get("default_temperature")
        if temperature is not None and (
            not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or float(temperature) < 0
        ):
            raise InvalidSettings("default_temperature must be a finite non-negative number")
