from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from local_asr_server.app_services import AppServices
from local_asr_server.llm import DEFAULT_GEMINI_MODEL, LLMService
from local_asr_server.env import get_env_var
from local_asr_server.runtime.llm_sidecar import LocalLLMSidecarError
from local_asr_server.runtime.models import ANALYSIS_QUALITY_DEFAULTS, resolve_local_llm_model_path
from local_asr_server.schemas import ANALYSIS_SETTING_OVERRIDE_FIELDS, AnalysisRequest
from local_asr_server.settings import load_settings
from local_asr_server.structured_notes import (
    StructuredNotesError,
    StructuredNotesInputTooLarge,
    generate_structured_notes,
    is_structured_notes_template,
    legacy_transcription_analysis,
)

logger = logging.getLogger("uvicorn.error")
ANALYSIS_CACHE_VERSION = "analysis-v1"
STRUCTURED_ANALYSIS_CACHE_VERSION = "analysis-structured-v2"


class AnalysisService:
    """Application service that owns analysis workflow decisions."""

    def __init__(self, services: AppServices) -> None:
        self.services = services

    def analyze(self, body: AnalysisRequest) -> dict[str, Any]:
        settings = self.settings_with_request_overrides(load_settings(), body)
        provider_name = settings.get("llm_provider", "mock")
        local_phase = provider_name in {"nemotron_local", "voxtral_local"}
        structured_notes = is_structured_notes_template(body.template_id)
        api_key = body.gemini_api_key or settings.get("gemini_api_key", "") or get_env_var("GEMINI_API_KEY")
        gemini_model = settings.get("gemini_model") or DEFAULT_GEMINI_MODEL
        local_llm_url = None
        local_llm_model = None
        temperature = self._resolve_temperature(settings)

        try:
            if local_phase:
                capability = (
                    "audio"
                    if provider_name == "voxtral_local" and body.recording_id and not structured_notes
                    else "text"
                )
                try:
                    runtime_options = self.services.runtime.ensure_llm_ready(
                        capability=capability,
                        reasoning=settings.get("local_llm_reasoning") or "auto",
                        overrides=settings,
                    )
                    local_llm_url = runtime_options.get("base_url")
                    local_llm_model = runtime_options.get("model")
                except LocalLLMSidecarError as exc:
                    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc
                except RuntimeError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

            effective_model = gemini_model if provider_name == "gemini" else local_llm_model
            provider = LLMService.get_provider(provider_name, api_key, local_llm_url, local_llm_model, gemini_model)

            if provider_name == "voxtral_local" and body.recording_id and not structured_notes:
                return self._analyze_audio(
                    body, provider, provider_name=provider_name,
                    model=local_llm_model, settings=settings,
                )
            return self._analyze_text(
                body, provider, provider_name=provider_name, model=effective_model,
                settings=settings, api_key=api_key, temperature=temperature,
            )
        finally:
            if local_phase:
                self.services.runtime.release_llm_residency(overrides=settings)

    @staticmethod
    def request_setting_overrides(body: Any) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        provided_fields = getattr(body, "model_fields_set", None)
        if provided_fields is None:
            provided_fields = getattr(body, "__fields_set__", None)
        tracks_provided_fields = provided_fields is not None
        provided_fields = provided_fields or set()
        for field in ANALYSIS_SETTING_OVERRIDE_FIELDS:
            if tracks_provided_fields and field not in provided_fields:
                continue
            value = getattr(body, field, None)
            if value is None:
                if tracks_provided_fields:
                    overrides[field] = None
                continue
            if isinstance(value, str) and not value.strip():
                continue
            overrides[field] = value
        return overrides

    @classmethod
    def settings_with_request_overrides(cls, settings: dict[str, Any], body: Any) -> dict[str, Any]:
        return {**settings, **cls.request_setting_overrides(body)}

    def _resolve_temperature(self, settings: dict[str, Any]) -> float:
        configured = settings.get("local_llm_temperature")
        if configured is not None and configured != "":
            try:
                return float(configured)
            except (TypeError, ValueError):
                pass
        preset = settings.get("local_llm_quality_preset") or "balanced"
        return float(getattr(ANALYSIS_QUALITY_DEFAULTS, preset, ANALYSIS_QUALITY_DEFAULTS.balanced))

    def _analyze_audio(
        self, body: AnalysisRequest, provider: Any, *, provider_name: str,
        model: str | None, settings: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            audio_path = self.services.recordings.audio_path(body.recording_id)
            if not hasattr(provider, "analyze_audio"):
                raise ValueError("Il provider selezionato non supporta l'analisi audio.")
            cache_key = self._cache_key(
                input_hash=self._hash_file(audio_path), provider_name=provider_name,
                model=model, settings=settings, audio_task=body.audio_task,
                question=body.question,
            )
            result = self._get_cached_analysis(cache_key)
            if result is None:
                result = provider.analyze_audio(
                    audio_path=audio_path,
                    task=body.audio_task or "analysis",
                    question=body.question,
                )
                result = self._normalize_result(result)
                self.services.catalog.save_analysis_cache(cache_key, result)
            else:
                result = self._normalize_result(result)
            if body.transcription_id:
                try:
                    self.services.transcriptions.save_analysis(body.transcription_id, result)
                except Exception as exc:
                    logger.error("Errore nel salvataggio dell'analisi audio: %s", exc)
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _analyze_text(
        self, body: AnalysisRequest, provider: Any, *, provider_name: str,
        model: str | None, settings: dict[str, Any], api_key: str,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        text_to_analyze = ""
        transcription: dict[str, Any] | None = None
        if body.transcription_id:
            try:
                transcription = self.services.transcriptions.get(body.transcription_id)
                text_to_analyze = transcription.get("text", "")
            except Exception as exc:
                raise HTTPException(status_code=404, detail="Trascrizione non trovata.") from exc
        elif body.recording_id:
            try:
                transcription = self.services.transcriptions.find_for_recording(body.recording_id)
                if not transcription:
                    raise LookupError("Trascrizione non trovata.")
                text_to_analyze = transcription.get("text", "")
            except Exception as exc:
                raise HTTPException(status_code=404, detail="Trascrizione non trovata per questa registrazione.") from exc
        elif body.text:
            text_to_analyze = body.text
        else:
            raise HTTPException(status_code=400, detail="Fornire transcription_id, recording_id o text per l'analisi testuale.")

        if not text_to_analyze.strip():
            raise HTTPException(status_code=400, detail="Il testo da analizzare è vuoto.")

        structured_notes = is_structured_notes_template(body.template_id)
        if structured_notes and transcription is None:
            transcription = {"text": text_to_analyze, "segments": []}
        try:
            input_hash = (
                self._structured_input_hash(transcription or {"text": text_to_analyze})
                if structured_notes
                else self._hash_text(text_to_analyze)
            )
            cache_key = self._cache_key(
                input_hash=input_hash, provider_name=provider_name,
                model=model, settings=settings, prompt=body.prompt,
                temperature=temperature, credential=api_key if provider_name == "gemini" else None,
                cache_version=STRUCTURED_ANALYSIS_CACHE_VERSION if structured_notes else ANALYSIS_CACHE_VERSION,
            )
            result = self._get_cached_analysis(cache_key)
            if result is None:
                if structured_notes:
                    result = generate_structured_notes(
                        provider,
                        transcription or {"text": text_to_analyze},
                        temperature=temperature,
                    )
                else:
                    result = provider.analyze(text_to_analyze, prompt=body.prompt, temperature=temperature)
                    result = self._normalize_result(result)
                self.services.catalog.save_analysis_cache(cache_key, result)
            else:
                result = self._normalize_result(result)
            if body.transcription_id:
                persisted = legacy_transcription_analysis(result) if structured_notes else result
                self.services.transcriptions.save_analysis(body.transcription_id, persisted)
            return result
        except StructuredNotesInputTooLarge as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "structured_notes_input_too_large", "message": str(exc)},
            ) from exc
        except StructuredNotesError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "structured_notes_invalid_result", "message": str(exc)},
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _get_cached_analysis(self, cache_key: str) -> dict[str, Any] | None:
        result = self.services.catalog.get_analysis_cache(cache_key)
        if result is not None:
            logger.info("[Analysis Cache] Hit for key %s", cache_key[:12])
        return result

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_file(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _structured_input_hash(cls, transcription: dict[str, Any]) -> str:
        segments = []
        for index, segment in enumerate(transcription.get("segments") or []):
            if not isinstance(segment, dict):
                continue
            segments.append(
                {
                    "id": segment.get("id", index),
                    "start": segment.get("start"),
                    "end": segment.get("end"),
                    "speaker": segment.get("speaker_name") or segment.get("speaker_label") or segment.get("speaker"),
                    "text": segment.get("text") or "",
                }
            )
        payload = {
            "text": transcription.get("text") or "",
            "segments": segments,
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return cls._hash_text(serialized)

    def _cache_key(
        self, *, input_hash: str, provider_name: str, model: str | None,
        settings: dict[str, Any], prompt: str | None = None,
        temperature: float | None = None, audio_task: str | None = None,
        question: str | None = None, credential: str | None = None,
        cache_version: str = ANALYSIS_CACHE_VERSION,
    ) -> str:
        """Hash every input and setting that can change an analysis result."""
        provider_options = {
            "provider": provider_name,
            "model": model or settings.get("local_llm_model") or "",
            "gemini_model": model if provider_name == "gemini" else "",
            "temperature": temperature,
            "quality_preset": settings.get("local_llm_quality_preset") or "balanced",
            "reasoning": settings.get("local_llm_reasoning") or "auto",
            "max_output_tokens": settings.get("local_llm_max_output_tokens"),
            "json_mode": settings.get("local_llm_json_mode", True),
            "backend": settings.get("local_llm_backend") or "",
            "model_path": resolve_local_llm_model_path(settings),
            "mmproj_path": settings.get("local_llm_mmproj_path") or "",
            "ctx_size": settings.get("local_llm_ctx_size"),
        }
        payload = {
            "version": cache_version,
            "input_hash": input_hash,
            "prompt": prompt or "",
            "audio_task": audio_task or "",
            "question": question or "",
            "provider_options": provider_options,
            # Hash credentials rather than writing secrets to the local catalog.
            "credential_hash": self._hash_text(credential) if credential else "",
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return self._hash_text(serialized)

    def _normalize_result(self, result: Any) -> dict[str, Any]:
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    result = parsed
            except Exception:
                pass

        if isinstance(result, str):
            return {"markdown": result}
        if isinstance(result, dict):
            if "markdown" in result:
                return result
            # Convert structured dict to markdown
            lines = []
            if result.get("title"):
                lines.append(f"# {result['title']}\n")
            if result.get("summary"):
                lines.append(f"## Riassunto\n{result['summary']}\n")
            if result.get("key_points"):
                lines.append("## Punti Chiave")
                for kp in result["key_points"]:
                    lines.append(f"- {kp}")
                lines.append("")
            if result.get("action_items"):
                lines.append("## Prossimi Passi")
                for ai in result["action_items"]:
                    lines.append(f"- {ai}")
                lines.append("")

            normalized = result.copy()
            normalized["markdown"] = "\n".join(lines)
            return normalized
        return {"markdown": str(result)}
