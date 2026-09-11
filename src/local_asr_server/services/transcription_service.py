from __future__ import annotations

from local_asr_server.app_services import get_services

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from local_asr_server.asr_provider import (
    ASR_PROVIDER_LOCAL,
    ASR_PROVIDER_SPEECHMATICS,
    ASRRequest,
    LocalMlxASRProvider,
    VAD_GUIDED_DEFAULT,
    VAD_POST_FILTER_DEFAULT,
    asr_backend_for,
    normalize_asr_provider,
    public_asr_metadata,
    public_provider_options,
    speechmatics_options_from_settings,
)
from local_asr_server.audio_intelligence import build_audio_intelligence
from local_asr_server.recordings import RecordingStore
from local_asr_server.routers.helpers import _merge_track_transcriptions
from local_asr_server.runtime.asr_worker import ASRWorkerRunner, InProcessASRWorkerRunner, ASRProcessRunner
from local_asr_server.schemas import TranscribeRecordingRequest
from local_asr_server.settings import load_settings
from local_asr_server.speechmatics_asr import SpeechmaticsBatchASRProvider
from local_asr_server.speaker_diarization import LocalSpeakerDiarizationService
from local_asr_server.transcription_diarization import (
    DIARIZATION_PROVIDER_DISABLED,
    DIARIZATION_PROVIDERS,
)
from local_asr_server.transcriber import (
    _clean_nan_values,
    generate_cache_key,
    get_cached_result,
    hash_audio_file,
    save_cached_result,
)
from local_asr_server.transcription_quality import audio_stats, is_near_silent_track
from local_asr_server.visual_intelligence import PostMeetingVisualService
from local_asr_server.diagnostics import attach_diagnostics, diagnostic, log_diagnostic
from local_asr_server.speaker_labels import apply_speaker_labels


logger = logging.getLogger("uvicorn.error")

RECORDING_PIPELINE_CACHE_VERSION = 2
RECORDING_PIPELINE_SETTING_KEYS = (
    "speaker_diarization_enabled",
    "speaker_diarization_minimum_overlap",
    "visual_intelligence_enabled",
    "visual_llm_model",
    "visual_routing_mode",
    "visual_frame_similarity_threshold",
    "visual_minimum_observations",
    "visual_minimum_margin",
    "visual_minimum_distinct_turns",
    "visual_minimum_temporal_support_seconds",
)


class TranscriptionService:
    """Application service boundary for transcription workflows."""

    def __init__(self, runner: ASRWorkerRunner | None = None) -> None:
        self.runner = runner or ASRProcessRunner()
        self.visual = PostMeetingVisualService()
        self.diarization = LocalSpeakerDiarizationService()

    def transcribe_file(self, **kwargs: Any) -> dict[str, Any]:
        provider_name = normalize_asr_provider(kwargs.pop("asr_provider", ASR_PROVIDER_LOCAL))
        request = ASRRequest(
            audio_path=kwargs["audio_path"],
            model=kwargs.get("model") or "",
            language=kwargs.get("language"),
            task=kwargs.get("task", "transcribe"),
            word_timestamps=bool(kwargs.get("word_timestamps", False)),
            initial_prompt=kwargs.get("initial_prompt"),
            temperature=kwargs.get("temperature"),
            condition_on_previous_text=bool(kwargs.get("condition_on_previous_text", False)),
            verbose=kwargs.get("verbose"),
            vad_guided=bool(kwargs.get("vad_guided", VAD_GUIDED_DEFAULT)),
            vad_post_filter=bool(kwargs.get("vad_post_filter", VAD_POST_FILTER_DEFAULT)),
            provider=provider_name,
            provider_options=kwargs.pop("provider_options", {}) or {},
            job=kwargs.get("job"),
            progress_callback=kwargs.get("progress_callback"),
            audio_duration_seconds=kwargs.get("audio_duration_seconds"),
        )
        if provider_name == ASR_PROVIDER_SPEECHMATICS:
            return SpeechmaticsBatchASRProvider().transcribe(request)
        return LocalMlxASRProvider(self.runner).transcribe(request)

    def transcribe_cached(
        self,
        audio_path: Path,
        *,
        engine: Callable[..., dict[str, Any]] | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        """Reuse one deterministic engine cache for every transcription entrypoint."""
        cache_key = self.cache_key(audio_path, **options)
        cached = get_cached_result(cache_key)
        if cached is not None:
            logger.info("[ASR Cache] Hit for %s", audio_path.name)
            return cached
        result = (engine or self.transcribe_file)(audio_path=str(audio_path), **options)
        save_cached_result(cache_key, result)
        return result

    @staticmethod
    def cache_key(audio_path: Path, **options: Any) -> str:
        provider = normalize_asr_provider(options.get("asr_provider"))
        provider_options = public_provider_options(provider, options.get("provider_options"))
        cache_options = {
            name: options[name]
            for name in (
                "model",
                "language",
                "task",
                "word_timestamps",
                "initial_prompt",
                "temperature",
                "condition_on_previous_text",
                "vad_guided",
                "vad_post_filter",
            )
        }
        cache_options.update(
            asr_provider=provider,
            backend=asr_backend_for(provider, options.get("model") or ""),
            provider_options=provider_options,
        )
        return generate_cache_key(audio_hash=hash_audio_file(audio_path), **cache_options)

    @staticmethod
    def resolve_asr(
        settings: dict[str, Any],
        *,
        provider: str | None = None,
        model: str | None = None,
        speechmatics_region: str | None = None,
        speechmatics_model: str | None = None,
        speechmatics_diarization: str | None = None,
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        selected_provider = normalize_asr_provider(provider or settings.get("asr_provider"))
        if selected_provider == ASR_PROVIDER_SPEECHMATICS:
            private_options = speechmatics_options_from_settings(
                settings,
                model=speechmatics_model,
                region=speechmatics_region,
                diarization=speechmatics_diarization,
            )
            selected_model = private_options["speechmatics_model"]
        else:
            private_options = {}
            selected_model = model or ""
        return (
            selected_provider,
            selected_model or "",
            private_options,
            public_provider_options(selected_provider, private_options),
        )

    @staticmethod
    def resolve_recording_defaults(
        body: TranscribeRecordingRequest,
        settings: dict[str, Any],
        *,
        fallback_model: str,
    ) -> TranscribeRecordingRequest:
        """Resolve omitted normal-path options from persisted settings without overriding explicit requests."""
        explicit_fields = body.model_fields_set
        defaults: dict[str, Any] = {
            "model": settings.get("default_model") or fallback_model,
            "language": settings.get("default_language", "it"),
            "task": settings.get("default_task") or "transcribe",
            "word_timestamps": bool(settings.get("default_word_timestamps", False)),
            "temperature": settings.get("default_temperature"),
            "condition_on_previous_text": bool(settings.get("default_condition_on_previous", False)),
        }
        updates = {
            field: value
            for field, value in defaults.items()
            if field not in explicit_fields
        }
        return body.model_copy(update=updates) if updates else body

    @staticmethod
    def backend(provider: str, model: str) -> str:
        return asr_backend_for(provider, model)

    @staticmethod
    def payload_metadata(provider: str, model: str, options: dict[str, Any]) -> dict[str, Any]:
        return public_asr_metadata(provider, model, options)

    def transcribe_recording(
        self,
        app: Any,
        recording_id: str,
        body: TranscribeRecordingRequest,
        job: Any | None = None,
        *,
        engine: Callable[..., dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        settings = load_settings()
        body = self.resolve_recording_defaults(
            body,
            settings,
            fallback_model=app.state.default_model,
        )
        visual_intelligence_enabled = (
            bool(body.visual_intelligence_enabled)
            if body.visual_intelligence_enabled is not None
            else bool(settings.get("visual_intelligence_enabled"))
        )
        pipeline_settings = {
            **settings,
            "visual_intelligence_enabled": visual_intelligence_enabled,
        }
        requested_diarization = body.diarization_provider
        selected_diarization_provider = (
            str(requested_diarization).strip().lower()
            if requested_diarization is not None
            else (
                ASR_PROVIDER_LOCAL
                if settings.get("speaker_diarization_enabled", False)
                else DIARIZATION_PROVIDER_DISABLED
            )
        )
        if (
            selected_diarization_provider != DIARIZATION_PROVIDER_DISABLED
            and selected_diarization_provider not in DIARIZATION_PROVIDERS
        ):
            raise ValueError(f"Unsupported diarization provider: {requested_diarization}")
        provider, provider_model, provider_options, public_options = self.resolve_asr(
            settings,
            provider=body.asr_provider,
            model=body.model or app.state.default_model,
            speechmatics_region=body.speechmatics_region,
            speechmatics_model=body.speechmatics_model,
            speechmatics_diarization=body.speechmatics_diarization,
        )
        target_model = provider_model or body.model or app.state.default_model
        store: RecordingStore = get_services(app).recordings
        recording = store.get(recording_id, include_result=False)
        track_paths = store.transcribable_tracks(recording_id)

        def job_event(
            status: str,
            step: str,
            progress: int,
            *,
            component_outcome: dict[str, Any] | None = None,
        ) -> None:
            if job is None:
                return
            if hasattr(app.state, "transcription_jobs"):
                get_services(app).transcription_jobs.update_progress(
                    job.id,
                    status,
                    progress,
                    step,
                    message=component_outcome.get("status") if component_outcome else None,
                    event_payload=component_outcome,
                )
                return
            job.status = status
            job.current_step = step
            job.progress = progress
            job.updated_at = time.time()
            job.events.put(job.public())

        job_event("validating_audio", "validating_audio", 10)
        track_results = []
        total_tracks = max(1, len(track_paths))
        for index, (track, audio_path) in enumerate(track_paths):
            if job and job.cancel_requested:
                raise RuntimeError("Transcription job cancelled")
            step = "transcribing_system" if track.get("id") == "system" else "transcribing_mic"
            job_event(step, step, 20 + int(index / total_tracks * 60))
            result, track_stats = self._inspect_track(audio_path, track)
            if result is None:
                track_started_at = time.perf_counter()

                def asr_progress(
                    detail: dict[str, Any],
                    *,
                    current_index: int = index,
                    current_track: dict[str, Any] = track,
                    current_step: str = step,
                    current_stats: dict[str, float] = track_stats,
                ) -> None:
                    elapsed = max(0.0, time.perf_counter() - track_started_at)
                    duration = float(current_stats.get("duration_seconds") or 0.0)
                    processed = min(duration, max(0.0, float(detail.get("processed_audio_seconds") or 0.0)))
                    track_percent = min(99, int((processed / duration) * 100)) if duration > 0 and processed > 0 else 0
                    eta = None
                    if processed > 0 and duration > processed:
                        eta = max(0.0, elapsed * ((duration - processed) / processed))
                    overall = 20 + int(((current_index + track_percent / 100) / total_tracks) * 60)
                    payload = {
                        "schema_version": 1,
                        "kind": "asr_track_progress",
                        "phase": detail.get("phase") or "transcribing",
                        "track_id": current_track.get("id"),
                        "track_label": current_track.get("label") or current_track.get("id"),
                        "track_index": current_index + 1,
                        "track_count": total_tracks,
                        "processed_audio_seconds": round(processed, 2),
                        "audio_duration_seconds": round(duration, 2) if duration > 0 else None,
                        "track_percent": track_percent,
                        "elapsed_seconds": round(elapsed, 2),
                        "eta_seconds": round(eta, 2) if eta is not None else None,
                    }
                    job_event(current_step, current_step, overall, component_outcome=payload)

                result = self.transcribe_cached(
                    audio_path,
                    engine=engine,
                    model=target_model,
                    language=body.language,
                    task=body.task,
                    word_timestamps=body.word_timestamps,
                    initial_prompt=body.initial_prompt,
                    temperature=body.temperature,
                    condition_on_previous_text=body.condition_on_previous_text,
                    verbose=body.verbose,
                    vad_guided=body.vad_guided,
                    vad_post_filter=body.vad_post_filter,
                    asr_provider=provider,
                    provider_options=provider_options,
                    job=job,
                    progress_callback=asr_progress,
                    audio_duration_seconds=track_stats.get("duration_seconds"),
                )
            public_track = next(
                (item for item in recording.get("audio_tracks", []) if item.get("id") == track["id"]),
                track,
            )
            track_results.append({"track": public_track, "result": result})

        cached_pipeline = get_services(app).transcriptions.latest_for_recording(recording_id)
        frames = store.list_visual_frames(recording_id)
        visual_input_fingerprint = self.visual_input_fingerprint(frames)
        if not frames and cached_pipeline is not None:
            visual_input_fingerprint = cached_pipeline.get("stats", {}).get(
                "recording_pipeline_visual_input_fingerprint", visual_input_fingerprint,
            )
        pipeline_cache_key = self.recording_pipeline_cache_key(
            recording_id=recording_id,
            track_results=track_results,
            settings=pipeline_settings,
            visual_input_fingerprint=visual_input_fingerprint,
            diarization_provider=selected_diarization_provider,
            diarization_region=body.speechmatics_region,
            diarization_model=body.speechmatics_model,
        )
        if (
            cached_pipeline is not None
            and cached_pipeline.get("stats", {}).get("recording_pipeline_cache_key")
            == pipeline_cache_key
            and self.recording_pipeline_cache_reusable(cached_pipeline)
        ):
            logger.info("[Recording Pipeline Cache] Hit for %s", recording_id)
            job_event("merging", "merging", 94)
            cached_pipeline["saved_id"] = cached_pipeline["id"]
            cached_pipeline["saved_file_path"] = str(get_services(app).transcriptions.root)
            cached_pipeline.setdefault("stats", {})["recording_pipeline_cache_hit"] = True
            return cached_pipeline

        job_event("diarizing", "diarizing", 82)
        diarization = self._process_initial_diarization(
            app,
            store,
            recording_id,
            track_paths,
            track_results,
            provider=selected_diarization_provider,
            speechmatics_region=body.speechmatics_region,
            speechmatics_model=body.speechmatics_model,
        )
        job_event("diarizing", "diarizing", 83, component_outcome=diarization)
        job_event("merging", "merging", 85)
        payload = _merge_track_transcriptions(
            track_results,
            model=target_model,
            language=body.language,
            elapsed=time.perf_counter() - started_at,
            recording_id=recording_id,
            asr_provider=provider,
            backend=self.backend(provider, target_model),
            provider_options=public_options,
        )
        diarization_summary = {
            key: value for key, value in diarization.items() if key != "tracks"
        }
        payload["speaker_diarization"] = diarization_summary
        payload.setdefault("stats", {})["speaker_diarization"] = diarization_summary
        payload["stats"]["recording_pipeline_cache_key"] = pipeline_cache_key
        payload["stats"]["recording_pipeline_visual_input_fingerprint"] = visual_input_fingerprint
        payload["stats"]["recording_pipeline_cache_hit"] = False
        def visual_progress(detail: dict[str, Any]) -> None:
            if job and job.cancel_requested:
                raise RuntimeError("Transcription job cancelled")
            val = 88
            current = int(detail.get("processed") or 0)
            total = int(detail.get("total") or 0)
            if total > 0:
                val = 88 + int((current / total) * 2)
            job_event(
                "visual_processing", "visual_processing", val,
                component_outcome=detail,
            )

        if visual_intelligence_enabled:
            job_event("visual_processing", "visual_processing", 88)
            payload = self.visual.process(
                get_services(app), recording_id, payload, progress_callback=visual_progress,
                enabled=True,
            )
            visual_outcome = payload.get("stats", {}).get("visual_intelligence")
            if visual_outcome:
                job_event("visual_processing", "visual_processing", 90, component_outcome=visual_outcome)
        else:
            # A per-run opt-out must not enter the visual service or emit image
            # progress. Captured frames remain staged for a future enabled run.
            store.finish_visual_processing(recording_id)
        if payload.get("speaker_attribution"):
            payload.setdefault("stats", {})["speaker_attribution"] = payload["speaker_attribution"]
        payload = apply_speaker_labels(payload)
        job_event("audio_intelligence", "audio_intelligence", 92)
        payload = self._attach_audio_intelligence(store, recording_id, track_paths, payload)
        audio_outcome = payload.get("stats", {}).get("audio_intelligence")
        if audio_outcome:
            job_event("audio_intelligence", "audio_intelligence", 93, component_outcome=audio_outcome)
        diagnostics = self._collect_diagnostics(track_results, payload)
        for item in diagnostics:
            log_diagnostic(
                logger,
                item,
                recording_id=recording_id,
                job_id=getattr(job, "id", None),
            )
        payload = attach_diagnostics(payload, diagnostics)
        payload = _clean_nan_values(payload)
        job_event("saving", "saving", 95)
        saved_meta = get_services(app).transcriptions.save(
            payload,
            audio_filename=recording.get("title")
            or Path(recording.get("audio_file") or "recording").name,
            recording_id=recording_id,
        )
        payload["saved_id"] = saved_meta["id"]
        payload["saved_file_path"] = str(get_services(app).transcriptions.root)
        return payload

    @staticmethod
    def recording_pipeline_cache_reusable(payload: dict[str, Any]) -> bool:
        """Retry post-ASR enrichments when a prior run retained inputs after backend failure."""
        visual = payload.get("stats", {}).get("visual_intelligence") or {}
        return not bool((visual.get("details") or {}).get("staging_preserved"))

    @staticmethod
    def recording_pipeline_cache_key(
        *,
        recording_id: str,
        track_results: list[dict[str, Any]],
        settings: dict[str, Any],
        visual_input_fingerprint: str,
        diarization_provider: str | None = None,
        diarization_region: str | None = None,
        diarization_model: str | None = None,
    ) -> str:
        """Fingerprint every input that affects post-ASR segment organization."""
        material = {
            "version": RECORDING_PIPELINE_CACHE_VERSION,
            "recording_id": recording_id,
            "track_results": track_results,
            "settings": {key: settings.get(key) for key in RECORDING_PIPELINE_SETTING_KEYS},
            "diarization": {
                "provider": diarization_provider,
                "region": diarization_region,
                "model": diarization_model,
            },
            "visual_input_fingerprint": visual_input_fingerprint,
        }
        encoded = json.dumps(
            _clean_nan_values(material), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _process_initial_diarization(
        app: Any,
        store: RecordingStore,
        recording_id: str,
        track_paths: list[tuple[dict[str, Any], Path]],
        track_results: list[dict[str, Any]],
        *,
        provider: str,
        speechmatics_region: str | None,
        speechmatics_model: str | None,
    ) -> dict[str, Any]:
        if provider == DIARIZATION_PROVIDER_DISABLED:
            return {
                "status": "disabled",
                "provider": provider,
                **diagnostic("speaker_diarization", "disabled"),
            }

        paths_by_id = {str(track["id"]): path for track, path in track_paths}
        assigned_by_track: dict[str, int] = {}
        clusters_by_track: dict[str, list[str]] = {}
        summaries: list[dict[str, Any]] = []
        try:
            for item in track_results:
                track_id = str(item["track"]["id"])
                result = item["result"]
                if track_id == "mic":
                    assigned = 0
                    for segment in result.get("segments") or []:
                        segment["track_id"] = track_id
                        segment["provider_speaker"] = "mic:S1"
                        segment["speaker_label"] = str(
                            item["track"].get("label") or item["track"].get("source") or "Tu"
                        )
                        assigned += 1
                    assigned_by_track[track_id] = assigned
                    clusters_by_track[track_id] = ["mic:S1"] if assigned else []
                    continue
                audio_path = paths_by_id.get(track_id)
                if audio_path is None:
                    continue
                updated = get_services(app).diarization.process_audio_payload(
                    audio_path,
                    {
                        **result,
                        "language": result.get("language"),
                        "stats": {},
                    },
                    provider=provider,
                    track_id=track_id,
                    speechmatics_region=speechmatics_region,
                    speechmatics_model=speechmatics_model,
                )
                item["result"] = {
                    **result,
                    "segments": updated.get("segments") or [],
                    "metadata": updated.get("metadata") or result.get("metadata") or {},
                }
                summary = updated.get("stats", {}).get("speaker_diarization") or {}
                summaries.append(summary)
                assigned_by_track[track_id] = int(summary.get("assigned_segments") or 0)
                clusters_by_track[track_id] = list(
                    (summary.get("clusters_by_track") or {}).get(track_id) or []
                )

            engine = next(
                (str(summary.get("engine")) for summary in summaries if summary.get("engine")),
                provider,
            )
            combined = {
                "status": "completed",
                "engine": engine,
                "provider": provider,
                "assigned_segments": sum(assigned_by_track.values()),
                "assigned_segments_by_track": assigned_by_track,
                "cluster_count": sum(len(items) for items in clusters_by_track.values()),
                "clusters_by_track": clusters_by_track,
                "text_preserved": True,
                "rerun": False,
                **diagnostic(
                    "speaker_diarization",
                    "completed",
                    requested_backend=engine,
                    actual_backend=engine,
                    counts={
                        "assigned_segments": sum(assigned_by_track.values()),
                        "clusters": sum(len(items) for items in clusters_by_track.values()),
                        "tracks": len(assigned_by_track),
                    },
                    details={"provider": provider, "text_preserved": True},
                ),
            }
            store.save_speaker_diarization(recording_id, combined)
            return combined
        except Exception as exc:
            logger.warning("Initial diarization failed for recording %s: %s", recording_id, exc)
            failure = {
                "status": "failed",
                "provider": provider,
                **diagnostic(
                    "speaker_diarization",
                    "failed",
                    requested_backend=provider,
                    error=str(exc),
                    details={"provider": provider, "text_preserved": True},
                ),
            }
            store.save_speaker_diarization(recording_id, failure)
            return failure

    @staticmethod
    def visual_input_fingerprint(frames: list[dict[str, Any]]) -> str:
        visual_inputs = []
        for frame in frames:
            path = Path(frame["path"])
            visual_inputs.append({
                "sequence": int(frame["sequence"]),
                "timestamp": float(frame["timestamp"]),
                "sha256": hash_audio_file(path),
            })
        encoded = json.dumps(
            visual_inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _inspect_track(
        audio_path: Path,
        track: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, float]]:
        try:
            from local_asr_server.audio_intelligence.audio_io import load_audio_samples

            stats = audio_stats(load_audio_samples(audio_path))
        except Exception as exc:
            logger.info(
                "[ASR Quality] Cannot inspect track %s; continuing with ASR: %s",
                track.get("id"),
                exc,
            )
            return None, {}
        if not is_near_silent_track(stats):
            return None, stats
        logger.warning(
            "[ASR Quality] Skipping near-silent track %s: rms=%.6f peak=%.6f",
            track.get("id"),
            stats["rms"],
            stats["peak"],
        )
        return {
            "text": "",
            "segments": [],
            "metadata": {
                "skipped": True,
                "skip_reason": "near_silent_track",
                "audio_stats": stats,
            },
        }, stats

    @staticmethod
    def _attach_audio_intelligence(
        store: RecordingStore,
        recording_id: str,
        track_paths: list[tuple[dict[str, Any], Path]],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            intelligence = build_audio_intelligence(track_paths, payload.get("segments", []))
            store.save_intelligence(recording_id, intelligence)
            payload["segments"] = intelligence.get("segments", payload.get("segments", []))
            payload["insight_candidates"] = intelligence.get("insight_candidates", [])
            unavailable_channels = [
                channel
                for channel, details in (intelligence.get("channels") or {}).items()
                if not details.get("available", True)
            ]
            audio_degraded = bool(intelligence.get("fallback_used") or unavailable_channels)
            payload.setdefault("stats", {})["audio_intelligence"] = {
                "enabled": True,
                "version": intelligence.get("version"),
                "backend": intelligence.get("backend"),
                "mode": intelligence.get("mode"),
                "mock_insights": True,
                "speaking_time_pct": intelligence.get("conversation_metrics", {}).get("speaking_time_pct", {}),
                "long_pause_count": len(intelligence.get("conversation_metrics", {}).get("long_pauses", []) or []),
                "overlap_count": len(intelligence.get("conversation_metrics", {}).get("overlaps", []) or []),
                **diagnostic(
                    "audio_intelligence",
                    "degraded" if audio_degraded else "completed",
                    requested_backend=intelligence.get("requested_backend"),
                    actual_backend=intelligence.get("actual_backend"),
                    fallback_used=bool(intelligence.get("fallback_used")),
                    fallback_reason=intelligence.get("fallback_reason")
                    or (f"unavailable_channels: {', '.join(unavailable_channels)}" if unavailable_channels else None),
                    counts={
                        "channels": len(intelligence.get("channels", {})),
                        "unavailable_channels": len(unavailable_channels),
                    },
                ),
            }
        except Exception as exc:
            logger.warning("Audio intelligence failed for recording %s: %s", recording_id, exc)
            payload.setdefault("stats", {})["audio_intelligence"] = {
                "enabled": False,
                **diagnostic(
                    "audio_intelligence",
                    "failed",
                    requested_backend="silero-vad-v4",
                    error=str(exc),
                ),
            }
        return payload

    @staticmethod
    def _collect_diagnostics(
        track_results: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in track_results:
            track_id = str(item.get("track", {}).get("id") or "audio")
            metadata = item.get("result", {}).get("metadata", {}) or {}
            if metadata.get("skipped"):
                items.append(
                    diagnostic(
                        f"asr:{track_id}",
                        "skipped",
                        fallback_reason=metadata.get("skip_reason"),
                        counts={"segments": 0},
                    )
                )
            elif metadata.get("vad_fallback") or metadata.get("vad_filter_fallback"):
                items.append(
                    diagnostic(
                        f"asr:{track_id}",
                        "degraded",
                        requested_backend="vad_guided",
                        actual_backend="full_track_asr",
                        fallback_used=True,
                        fallback_reason=metadata.get("vad_fallback_reason")
                        or metadata.get("vad_filter_fallback"),
                        counts={"segments": len(item.get("result", {}).get("segments", []) or [])},
                    )
                )
        stats = payload.get("stats", {}) or {}
        for key in ("speaker_diarization", "visual_intelligence", "audio_intelligence"):
            value = stats.get(key)
            if isinstance(value, dict) and value.get("component"):
                items.append(value)
        return items
