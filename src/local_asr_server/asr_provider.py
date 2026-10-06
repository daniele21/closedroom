from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final, Protocol

from local_asr_server.asr_models import get_asr_backend
from local_asr_server.env import get_env_var
from local_asr_server.runtime.leases import ModelRuntimeLeaseManager


ASR_PROVIDER_LOCAL: Final = "local"
ASR_PROVIDER_SPEECHMATICS: Final = "speechmatics"
ASR_PROVIDERS: Final = (ASR_PROVIDER_LOCAL, ASR_PROVIDER_SPEECHMATICS)

SPEECHMATICS_BACKEND: Final = "speechmatics-batch"
SPEECHMATICS_REGION_EU: Final = "eu"
SPEECHMATICS_REGION_US: Final = "us"
SPEECHMATICS_REGION_URLS: Final = {
    SPEECHMATICS_REGION_EU: "https://asr.api.speechmatics.com/v2",
    SPEECHMATICS_REGION_US: "https://asr.api.us.speechmatics.com/v2",
}
SPEECHMATICS_MODELS: Final = ("standard", "enhanced")
SPEECHMATICS_DIARIZATION_MODES: Final = ("none", "speaker")
DEFAULT_SPEECHMATICS_REGION: Final = SPEECHMATICS_REGION_EU
DEFAULT_SPEECHMATICS_MODEL: Final = "standard"
DEFAULT_SPEECHMATICS_DIARIZATION: Final = "none"
VAD_GUIDED_DEFAULT: Final = True
VAD_POST_FILTER_DEFAULT: Final = True


@dataclass(frozen=True)
class ASRRequest:
    audio_path: str | Path
    model: str
    language: str | None = None
    task: str = "transcribe"
    word_timestamps: bool = False
    initial_prompt: str | None = None
    temperature: float | None = None
    condition_on_previous_text: bool = False
    verbose: bool | None = None
    vad_guided: bool = VAD_GUIDED_DEFAULT
    vad_post_filter: bool = VAD_POST_FILTER_DEFAULT
    provider: str = ASR_PROVIDER_LOCAL
    provider_options: dict[str, Any] = field(default_factory=dict)
    job: Any = None
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    audio_duration_seconds: float | None = None


class ASRProvider(Protocol):
    def transcribe(self, request: ASRRequest) -> dict[str, Any]:
        ...


class LocalMlxASRProvider:
    def __init__(
        self,
        runner: Any,
        *,
        model_phases: ModelRuntimeLeaseManager | None = None,
    ) -> None:
        self.runner = runner
        self.model_phases = model_phases or ModelRuntimeLeaseManager()

    def transcribe(self, request: ASRRequest) -> dict[str, Any]:
        self.model_phases.acquire_lease("asr")
        try:
            result = self.runner.transcribe(
                audio_path=str(request.audio_path),
                model=request.model,
                language=request.language,
                task=request.task,
                word_timestamps=request.word_timestamps,
                initial_prompt=request.initial_prompt,
                temperature=request.temperature,
                condition_on_previous_text=request.condition_on_previous_text,
                verbose=request.verbose,
                vad_guided=request.vad_guided,
                vad_post_filter=request.vad_post_filter,
                job=request.job,
                progress_callback=request.progress_callback,
                audio_duration_seconds=request.audio_duration_seconds,
            )
            payload = dict(result or {})
            payload.setdefault("model", request.model)
            payload.setdefault("backend", get_asr_backend(request.model))
            payload.setdefault("provider", ASR_PROVIDER_LOCAL)
            payload.setdefault("asr_provider", ASR_PROVIDER_LOCAL)
            metadata = dict(payload.get("metadata") or {})
            metadata.setdefault("asr_provider", ASR_PROVIDER_LOCAL)
            metadata.setdefault("backend", payload["backend"])
            payload["metadata"] = metadata
            return payload
        finally:
            self.model_phases.release_lease("asr")


def normalize_asr_provider(provider: str | None) -> str:
    value = (provider or ASR_PROVIDER_LOCAL).strip().lower()
    if value not in ASR_PROVIDERS:
        raise ValueError(f"Unsupported ASR provider: {provider}")
    return value


def public_provider_options(provider: str, options: dict[str, Any] | None) -> dict[str, Any]:
    cleaned = {
        key: value
        for key, value in (options or {}).items()
        if key not in {"api_key", "speechmatics_api_key", "authorization", "headers"}
        and value is not None
        and value != ""
    }
    if provider == ASR_PROVIDER_LOCAL:
        return {}
    return cleaned


def asr_backend_for(provider: str, model: str) -> str:
    normalized_provider = normalize_asr_provider(provider)
    return SPEECHMATICS_BACKEND if normalized_provider == ASR_PROVIDER_SPEECHMATICS else get_asr_backend(model)


def asr_model_for(provider: str, model: str | None, provider_options: dict[str, Any] | None = None) -> str:
    normalized_provider = normalize_asr_provider(provider)
    public_options = public_provider_options(normalized_provider, provider_options)
    if normalized_provider == ASR_PROVIDER_SPEECHMATICS:
        return str(public_options.get("speechmatics_model") or model or DEFAULT_SPEECHMATICS_MODEL)
    return model or ""


def public_asr_metadata(provider: str, model: str | None, provider_options: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_provider = normalize_asr_provider(provider)
    public_options = public_provider_options(normalized_provider, provider_options)
    resolved_model = asr_model_for(normalized_provider, model, public_options)
    return {
        "asr_provider": normalized_provider,
        "backend": asr_backend_for(normalized_provider, resolved_model),
        "model": resolved_model,
        "provider_options": public_options,
    }


def speechmatics_options_from_settings(
    settings: dict[str, Any],
    *,
    model: str | None = None,
    region: str | None = None,
    diarization: str | None = None,
) -> dict[str, Any]:
    selected_model = model or settings.get("speechmatics_model") or DEFAULT_SPEECHMATICS_MODEL
    selected_region = region or settings.get("speechmatics_region") or DEFAULT_SPEECHMATICS_REGION
    selected_diarization = diarization or settings.get("speechmatics_diarization") or DEFAULT_SPEECHMATICS_DIARIZATION
    if selected_region not in SPEECHMATICS_REGION_URLS:
        raise ValueError(f"Unsupported Speechmatics region: {selected_region}")
    if selected_model not in SPEECHMATICS_MODELS:
        raise ValueError(f"Unsupported Speechmatics model: {selected_model}")
    if selected_diarization not in SPEECHMATICS_DIARIZATION_MODES:
        raise ValueError(f"Unsupported Speechmatics diarization: {selected_diarization}")
    return {
        "api_key": settings.get("speechmatics_api_key", "") or get_env_var("SPEECHMATICS_API_KEY"),
        "region": selected_region,
        "url": SPEECHMATICS_REGION_URLS[selected_region],
        "speechmatics_model": selected_model,
        "speechmatics_diarization": selected_diarization,
        "timeout_seconds": settings.get("speechmatics_timeout_seconds"),
        "poll_interval_seconds": settings.get("speechmatics_poll_interval_seconds"),
    }


def asr_catalog(settings: dict[str, Any], default_model: str = "") -> dict[str, Any]:
    return {
        "default_provider": settings.get("asr_provider") or ASR_PROVIDER_LOCAL,
        "default_model": default_model,
        "providers": [
            {
                "id": ASR_PROVIDER_LOCAL,
                "label": "Local MLX",
                "cloud": False,
                "models": [],
            },
            {
                "id": ASR_PROVIDER_SPEECHMATICS,
                "label": "Speechmatics Batch",
                "cloud": True,
                "models": list(SPEECHMATICS_MODELS),
                "regions": [
                    {"id": region, "url": url}
                    for region, url in SPEECHMATICS_REGION_URLS.items()
                ],
                "diarization_modes": list(SPEECHMATICS_DIARIZATION_MODES),
                "api_key_configured": bool(settings.get("speechmatics_api_key") or get_env_var("SPEECHMATICS_API_KEY")),
            },
        ],
    }
