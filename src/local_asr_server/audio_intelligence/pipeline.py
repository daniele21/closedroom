from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from local_asr_server.audio_intelligence.audio_io import (
    canonical_wav_info,
    energy_windows_from_samples,
    iter_energy_windows,
    iter_normalized_audio_chunks,
    load_audio_samples,
)
from local_asr_server.audio_intelligence.features import (
    MAX_SERIALIZED_EVENTS,
    build_error_track_features,
    build_mock_insights,
    build_track_features,
    enrich_segments,
    summarize_conversation,
    format_vad_speech_windows,
)

logger = logging.getLogger("uvicorn.error")

INTELLIGENCE_VERSION = 1
ENERGY_BACKEND = "energy-rms-v1"
VAD_BACKEND = "silero-vad-v4"


def build_audio_intelligence(
    track_paths: list[tuple[dict[str, Any], Path]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    tracks = []
    backend_used = VAD_BACKEND
    fallback_reasons: list[str] = []
    channel_backends: dict[str, dict[str, Any]] = {}
    
    use_vad = True
    try:
        from local_asr_server.audio_intelligence.vad import (
            detect_speech_windows_vad,
            detect_speech_windows_vad_chunks,
        )
    except Exception as e:
        logger.warning(f"Could not load VAD backend, falling back to RMS: {e}")
        use_vad = False
        backend_used = ENERGY_BACKEND
        fallback_reasons.append(f"vad_backend_unavailable: {e}")

    for track, path in track_paths:
        track_id = str(track.get("id") or track.get("source") or "audio")
        track_backend = ENERGY_BACKEND if not use_vad else VAD_BACKEND
        track_fallback_reason = fallback_reasons[0] if not use_vad and fallback_reasons else None
        try:
            windows = None
            track_features = None
            if use_vad:
                try:
                    canonical = canonical_wav_info(path)
                    if canonical is not None:
                        # Native ClosedRoom audio stays bounded: RMS windows and
                        # Silero both stream from disk instead of materializing a
                        # multi-hour float32 track in the API process.
                        windows = list(iter_energy_windows(path))
                        raw_speech = detect_speech_windows_vad_chunks(
                            iter_normalized_audio_chunks(path, chunk_samples=512),
                            total_samples=canonical.sample_count,
                            sr=canonical.sample_rate,
                        )
                    else:
                        # Imported audio preserves the previous decode/resample
                        # path because its energy semantics may differ.
                        samples = load_audio_samples(path)
                        windows = list(iter_energy_windows(path))
                        raw_speech = detect_speech_windows_vad(samples, sr=16000)
                    duration = windows[-1].end if windows else 0.0
                    source = track.get("source") or track.get("id") or "audio"
                    speech_windows = format_vad_speech_windows(
                        raw_speech, windows, channel=source, duration=duration
                    )
                    track_features = build_track_features(
                        track, windows, speech_windows=speech_windows, threshold=0.5
                    )
                except Exception as vad_exc:
                    logger.warning(f"VAD failed for track {track.get('id')}, falling back to RMS: {vad_exc}")
                    backend_used = ENERGY_BACKEND
                    track_backend = ENERGY_BACKEND
                    track_fallback_reason = f"track_{track_id}_vad_failed: {vad_exc}"
                    fallback_reasons.append(track_fallback_reason)

            if windows is None:
                # Decode failures and installations without VAD preserve the
                # existing streaming RMS fallback rather than failing the track.
                windows = list(iter_energy_windows(path))
            if not windows and path.exists() and path.stat().st_size > 0:
                raise ValueError("audio_decode_empty")
            if track_features is None:
                track_features = build_track_features(track, windows)
                
            tracks.append(track_features)
            channel_backends[track_id] = {
                "requested_backend": VAD_BACKEND,
                "actual_backend": track_backend,
                "fallback_used": bool(track_fallback_reason),
                "fallback_reason": str(track_fallback_reason)[:500] if track_fallback_reason else None,
            }
        except Exception as exc:
            tracks.append(build_error_track_features(track, str(exc)))
            channel_backends[track_id] = {
                "requested_backend": VAD_BACKEND,
                "actual_backend": None,
                "fallback_used": False,
                "fallback_reason": None,
            }

    enriched_segments = enrich_segments(segments, tracks)
    metrics = summarize_conversation(tracks, enriched_segments)
    mock_insights = build_mock_insights(metrics)
    return {
        "version": INTELLIGENCE_VERSION,
        "backend": backend_used,
        "requested_backend": VAD_BACKEND,
        "actual_backend": backend_used,
        "fallback_used": bool(fallback_reasons),
        "fallback_reason": "; ".join(fallback_reasons)[:500] if fallback_reasons else None,
        "mode": "metadata_only",
        "channels": {
            track.source: {
                "track_id": track.track_id,
                "label": track.label,
                "available": track.error is None,
                "error": track.error,
                "duration_seconds": round(track.duration_seconds, 3),
                "speech_threshold": round(track.threshold, 6),
                **channel_backends.get(track.track_id, channel_backends.get(track.source, {})),
            }
            for track in tracks
        },
        "speech_windows": [
            window
            for track in tracks
            for window in track.speech_windows
        ][:MAX_SERIALIZED_EVENTS],
        "segments": enriched_segments,
        "conversation_metrics": metrics,
        "insight_candidates": mock_insights,
        "mock": True,
    }
