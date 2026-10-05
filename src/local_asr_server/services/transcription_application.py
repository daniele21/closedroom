from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from local_asr_server.app_services import get_services
from local_asr_server.services.transcription_service import TranscriptionService
from local_asr_server.transcriber import (
    _clean_nan_values,
    generate_cache_key,
    get_cached_result,
    hash_audio_file,
    save_cached_result,
)
from local_asr_server.transcription_diarization import DIARIZATION_PROVIDER_DISABLED


@dataclass(frozen=True, slots=True)
class SingleFileTranscriptionRequest:
    model: str
    language: str | None
    task: str
    word_timestamps: bool
    initial_prompt: str | None
    temperature: float | None
    condition_on_previous_text: bool
    verbose: bool | None
    vad_guided: bool
    vad_post_filter: bool
    asr_provider: str
    provider_options: dict[str, Any]
    public_provider_options: dict[str, Any]
    diarization_provider: str = DIARIZATION_PROVIDER_DISABLED
    diarization_region: str | None = None
    diarization_model: str | None = None


class SingleFileTranscriptionUseCase:
    """Own cache -> ASR -> diarization -> persistence for one audio file.

    HTTP upload/path adapters are responsible for obtaining a local Path and
    formatting the response. This use case owns the application decisions that
    must stay identical across those adapters.
    """

    def __init__(self, transcription: TranscriptionService) -> None:
        self.transcription = transcription

    def cache_key(self, audio_path: Path, request: SingleFileTranscriptionRequest) -> str:
        return generate_cache_key(
            audio_hash=hash_audio_file(audio_path),
            model=request.model,
            language=request.language,
            task=request.task,
            word_timestamps=request.word_timestamps,
            initial_prompt=request.initial_prompt,
            temperature=request.temperature,
            condition_on_previous_text=request.condition_on_previous_text,
            vad_guided=request.vad_guided,
            vad_post_filter=request.vad_post_filter,
            asr_provider=request.asr_provider,
            backend=self.transcription.backend(request.asr_provider, request.model),
            provider_options=request.public_provider_options,
            diarization_provider=request.diarization_provider,
            diarization_region=request.diarization_region,
            diarization_model=request.diarization_model,
        )

    def run(
        self,
        app: Any,
        audio_path: Path,
        request: SingleFileTranscriptionRequest,
        *,
        audio_filename: str | None,
        recording_id: str | None,
        engine: Callable[..., dict[str, Any]] | None = None,
        started_at: float | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter() if started_at is None else started_at
        cache_key = self.cache_key(audio_path, request)
        cached = get_cached_result(cache_key)

        if cached is not None:
            payload = {
                **cached,
                "language": cached.get("language", request.language),
                "model": cached.get("model", request.model),
                "backend": cached.get(
                    "backend",
                    self.transcription.backend(request.asr_provider, request.model),
                ),
                "asr_provider": cached.get("asr_provider", request.asr_provider),
                "provider_options": cached.get(
                    "provider_options", request.public_provider_options,
                ),
                "stats": cached.get("stats", {"time_total_seconds": 0.0}),
            }
        else:
            runner = engine or self.transcription.transcribe_file
            result = runner(
                audio_path=str(audio_path),
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
                asr_provider=request.asr_provider,
                provider_options=request.provider_options,
            )
            elapsed = time.perf_counter() - started_at
            payload = _clean_nan_values({
                "text": result.get("text", ""),
                "language": result.get("language", request.language),
                "segments": result.get("segments", []),
                "metadata": result.get("metadata", {}),
                "model": result.get("model", request.model),
                "backend": result.get(
                    "backend",
                    self.transcription.backend(request.asr_provider, request.model),
                ),
                "asr_provider": request.asr_provider,
                "provider_options": request.public_provider_options,
                "recording_id": recording_id or "",
                "stats": {
                    "time_total_seconds": elapsed,
                    **self.transcription.payload_metadata(
                        request.asr_provider,
                        request.model,
                        request.public_provider_options,
                    ),
                },
            })

        payload = self._apply_diarization(app, audio_path, payload, request)
        payload["recording_id"] = recording_id or payload.get("recording_id", "")
        if cached is None:
            save_cached_result(cache_key, payload)

        stored = get_services(app).transcriptions
        saved_meta = stored.save(
            payload,
            audio_filename=audio_filename,
            recording_id=recording_id,
        )
        payload["saved_id"] = saved_meta["id"]
        payload["saved_file_path"] = str(stored.root)
        return payload

    @staticmethod
    def _apply_diarization(
        app: Any,
        audio_path: Path,
        payload: dict[str, Any],
        request: SingleFileTranscriptionRequest,
    ) -> dict[str, Any]:
        if request.diarization_provider == DIARIZATION_PROVIDER_DISABLED:
            return payload
        existing = payload.get("stats", {}).get("speaker_diarization") or {}
        if (
            existing.get("status") == "completed"
            and existing.get("provider") == request.diarization_provider
        ):
            return payload
        return get_services(app).diarization.process_audio_payload(
            audio_path,
            payload,
            provider=request.diarization_provider,
            speechmatics_region=request.diarization_region,
            speechmatics_model=request.diarization_model,
        )
