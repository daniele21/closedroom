from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Final

from local_asr_server.asr_provider import (
    ASR_PROVIDER_LOCAL,
    ASR_PROVIDER_SPEECHMATICS,
    ASRRequest,
    DEFAULT_SPEECHMATICS_MODEL,
    normalize_asr_provider,
    speechmatics_options_from_settings,
)
from local_asr_server.diagnostics import attach_diagnostics, diagnostic
from local_asr_server.settings import load_settings
from local_asr_server.runtime.leases import ModelRuntimeLeaseManager
from local_asr_server.speaker_diarization import (
    DIARIZATION_ENGINE,
    LocalSpeakerDiarizationService,
    assigned_clusters,
    clusters_from_timeline,
)
from local_asr_server.speaker_labels import apply_speaker_labels
from local_asr_server.speechmatics_asr import SpeechmaticsBatchASRProvider


SPEECHMATICS_DIARIZATION_ENGINE: Final = "speechmatics-batch-diarization"
DIARIZATION_PROVIDER_DISABLED: Final = "none"
DIARIZATION_PROVIDERS: Final = (ASR_PROVIDER_LOCAL, ASR_PROVIDER_SPEECHMATICS)


class TranscriptionDiarizationService:
    """Replace speaker clusters on an existing transcript without rerunning its ASR."""

    def __init__(
        self,
        *,
        local_service: LocalSpeakerDiarizationService | None = None,
        speechmatics_provider: Any | None = None,
        model_phases: ModelRuntimeLeaseManager | None = None,
    ) -> None:
        self.local = local_service or LocalSpeakerDiarizationService(
            model_phases=model_phases,
        )
        self.speechmatics = speechmatics_provider or SpeechmaticsBatchASRProvider()

    def process_audio_payload(
        self,
        audio_path: Path,
        payload: dict[str, Any],
        *,
        provider: str,
        track_id: str = "system",
        speechmatics_region: str | None = None,
        speechmatics_model: str | None = None,
    ) -> dict[str, Any]:
        """Diarize an uploaded audio file while preserving the existing ASR payload."""
        selected_provider = normalize_asr_provider(provider)
        if selected_provider not in DIARIZATION_PROVIDERS:
            raise ValueError(f"Unsupported diarization provider: {provider}")

        started_at = time.perf_counter()
        updated = dict(payload)
        segments = [dict(segment) for segment in (payload.get("segments") or [])]
        existing_provider_timeline = [
            {
                "speaker": str(segment["provider_speaker"]),
                "start": float(segment.get("start") or 0.0),
                "end": float(segment.get("end") or segment.get("start") or 0.0),
            }
            for segment in segments
            if segment.get("provider_speaker")
        ]
        for segment in segments:
            segment["track_id"] = str(segment.get("track_id") or track_id)
            segment.pop("provider_speaker", None)
            segment.pop("speaker_name", None)

        settings = load_settings()
        minimum_overlap = float(settings.get("speaker_diarization_minimum_overlap", 0.25))
        if selected_provider == ASR_PROVIDER_LOCAL:
            result = self.local.diarize_paths({track_id: audio_path})
            engine = str(result.get("engine") or DIARIZATION_ENGINE)
            timeline = [
                {
                    "speaker": str(item["speaker"]),
                    "start": float(item.get("start") or 0.0),
                    "end": float(item.get("end") or item.get("start") or 0.0),
                }
                for item in ((result.get("tracks") or {}).get(track_id) or {}).get("segments", [])
                if item.get("speaker")
            ]
        elif existing_provider_timeline:
            engine = SPEECHMATICS_DIARIZATION_ENGINE
            timeline = existing_provider_timeline
        else:
            options = speechmatics_options_from_settings(
                settings,
                model=speechmatics_model,
                region=speechmatics_region,
                diarization="speaker",
            )
            result = self.speechmatics.transcribe(ASRRequest(
                audio_path=audio_path,
                model=str(options.get("speechmatics_model") or DEFAULT_SPEECHMATICS_MODEL),
                language=payload.get("language"),
                provider=ASR_PROVIDER_SPEECHMATICS,
                provider_options=options,
            ))
            engine = SPEECHMATICS_DIARIZATION_ENGINE
            timeline = [
                {
                    "speaker": str(segment["provider_speaker"]),
                    "start": float(segment.get("start") or 0.0),
                    "end": float(segment.get("end") or segment.get("start") or 0.0),
                }
                for segment in (result.get("segments") or [])
                if segment.get("provider_speaker")
            ]

        assigned = self.local.assign_segments(
            {"segments": segments},
            track_id,
            timeline,
            minimum_overlap,
        )
        if segments and not timeline:
            raise RuntimeError("No speaker clusters were returned for the uploaded audio.")

        clusters = clusters_from_timeline(track_id, timeline)
        assigned_cluster_ids = assigned_clusters(segments)
        unassigned_clusters = [
            cluster for cluster in clusters if cluster not in assigned_cluster_ids
        ]
        summary = {
            "status": "completed",
            "engine": engine,
            "provider": selected_provider,
            "assigned_segments": assigned,
            "assigned_segments_by_track": {track_id: assigned},
            "cluster_count": len(clusters),
            "clusters_by_track": {track_id: clusters},
            "assigned_cluster_count": len(assigned_cluster_ids),
            "unassigned_clusters_by_track": {track_id: unassigned_clusters},
            "text_preserved": True,
            "rerun": False,
            **diagnostic(
                "speaker_diarization",
                "completed",
                requested_backend=engine,
                actual_backend=engine,
                counts={
                    "assigned_segments": assigned,
                    "clusters": len(clusters),
                    "assigned_clusters": len(assigned_cluster_ids),
                    "tracks": 1,
                },
                duration_seconds=time.perf_counter() - started_at,
                details={
                    "provider": selected_provider,
                    "processed_tracks": [track_id],
                    "text_preserved": True,
                },
            ),
        }
        updated["segments"] = segments
        updated["speaker_diarization"] = summary
        stats = dict(updated.get("stats") or {})
        stats["speaker_diarization"] = summary
        updated["stats"] = stats
        updated = apply_speaker_labels(updated)
        return attach_diagnostics(updated, [
            *[
                item
                for item in (payload.get("diagnostics") or stats.get("diagnostics") or [])
                if item.get("component") != "speaker_diarization"
            ],
            summary,
        ])

    def run(
        self,
        recording_store: Any,
        transcription_store: Any,
        transcription_id: str,
        *,
        provider: str,
        speechmatics_region: str | None = None,
        speechmatics_model: str | None = None,
        progress_callback: Callable[[str, int, dict[str, Any] | None], None] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        selected_provider = normalize_asr_provider(provider)
        if selected_provider not in DIARIZATION_PROVIDERS:
            raise ValueError(f"Unsupported diarization provider: {provider}")

        original = transcription_store.get(transcription_id)
        recording_id = str(original.get("recording_id") or "")
        if not recording_id:
            raise ValueError("Only transcriptions linked to a recording can be re-diarized.")

        track_paths = recording_store.transcribable_tracks(recording_id)
        tracks_by_id = {str(track["id"]): (track, path) for track, path in track_paths}
        segments = [dict(segment) for segment in (original.get("segments") or [])]
        source_tracks = [dict(track) for track in (original.get("source_tracks") or [])]
        labels = {
            str(track.get("id")): str(track.get("label") or track.get("source") or "Audio")
            for track in source_tracks
        }

        grouped: dict[str, list[dict[str, Any]]] = {}
        for segment in segments:
            track_id = str(segment.get("track_id") or segment.get("source") or "mixed")
            segment["track_id"] = track_id
            segment.pop("provider_speaker", None)
            segment.pop("speaker_name", None)
            segment["speaker_label"] = labels.get(track_id, segment.get("source") or "Audio")
            grouped.setdefault(track_id, []).append(segment)

        mic_timeline = []
        for segment in grouped.get("mic", []):
            segment["provider_speaker"] = "mic:S1"
            mic_timeline.append({
                "speaker": "S1",
                "start": float(segment.get("start") or 0.0),
                "end": float(segment.get("end") or segment.get("start") or 0.0),
            })

        diarizable_ids = [
            track_id
            for track_id in grouped
            if track_id != "mic" and track_id in tracks_by_id
        ]
        if progress_callback:
            progress_callback(
                "preparing_diarization",
                10,
                {"provider": selected_provider, "tracks": diarizable_ids},
            )

        try:
            if selected_provider == ASR_PROVIDER_LOCAL:
                summary = self._run_local(
                    recording_store,
                    recording_id,
                    tracks_by_id,
                    grouped,
                    diarizable_ids,
                )
            else:
                summary = self._run_speechmatics(
                    recording_id,
                    tracks_by_id,
                    grouped,
                    diarizable_ids,
                    language=original.get("language"),
                    region=speechmatics_region,
                    model=speechmatics_model,
                    progress_callback=progress_callback,
                )
        except Exception as exc:
            engine = (
                SPEECHMATICS_DIARIZATION_ENGINE
                if selected_provider == ASR_PROVIDER_SPEECHMATICS
                else DIARIZATION_ENGINE
            )
            recording_store.save_speaker_diarization(recording_id, {
                **diagnostic(
                    "speaker_diarization",
                    "failed",
                    requested_backend=engine,
                    error=str(exc),
                    duration_seconds=time.perf_counter() - started_at,
                    details={
                        "provider": selected_provider,
                        "processed_tracks": diarizable_ids,
                        "text_preserved": True,
                    },
                ),
                "provider": selected_provider,
                "text_preserved": True,
                "rerun": True,
            })
            raise

        tracks = dict(summary.get("tracks") or {})
        if mic_timeline:
            tracks["mic"] = {"segments": mic_timeline}

        assigned_by_track = {
            track_id: sum(1 for segment in track_segments if segment.get("provider_speaker"))
            for track_id, track_segments in grouped.items()
        }
        clusters_by_track = {
            track_id: clusters_from_timeline(
                track_id,
                list((track_payload or {}).get("segments") or []),
            )
            for track_id, track_payload in tracks.items()
        }
        missing_cluster_tracks = [
            track_id
            for track_id in diarizable_ids
            if grouped.get(track_id) and not clusters_by_track.get(track_id)
        ]
        if missing_cluster_tracks:
            failure = {
                **diagnostic(
                    "speaker_diarization",
                    "failed",
                    requested_backend=(
                        SPEECHMATICS_DIARIZATION_ENGINE
                        if selected_provider == ASR_PROVIDER_SPEECHMATICS
                        else DIARIZATION_ENGINE
                    ),
                    error=(
                        "No speaker clusters were returned for track(s): "
                        + ", ".join(missing_cluster_tracks)
                    ),
                    details={
                        "provider": selected_provider,
                        "processed_tracks": diarizable_ids,
                        "text_preserved": True,
                    },
                ),
                "provider": selected_provider,
                "text_preserved": True,
                "rerun": True,
                "tracks": tracks,
            }
            recording_store.save_speaker_diarization(recording_id, failure)
            raise RuntimeError(
                "No speaker clusters were returned for track(s): "
                + ", ".join(missing_cluster_tracks)
            )
        cluster_count = sum(len(clusters) for clusters in clusters_by_track.values())
        assigned_segments = sum(assigned_by_track.values())
        assigned_cluster_ids = {
            cluster
            for track_segments in grouped.values()
            for cluster in assigned_clusters(track_segments)
        }
        unassigned_clusters_by_track = {
            track_id: [
                cluster for cluster in clusters if cluster not in assigned_cluster_ids
            ]
            for track_id, clusters in clusters_by_track.items()
        }
        engine = (
            SPEECHMATICS_DIARIZATION_ENGINE
            if selected_provider == ASR_PROVIDER_SPEECHMATICS
            else summary.get("engine") or DIARIZATION_ENGINE
        )
        public_summary = {
            "status": "completed",
            "engine": engine,
            "provider": selected_provider,
            "assigned_segments": assigned_segments,
            "assigned_segments_by_track": assigned_by_track,
            "cluster_count": cluster_count,
            "clusters_by_track": clusters_by_track,
            "assigned_cluster_count": len(assigned_cluster_ids),
            "unassigned_clusters_by_track": unassigned_clusters_by_track,
            "text_preserved": True,
            "rerun": True,
            **diagnostic(
                "speaker_diarization",
                "completed",
                requested_backend=engine,
                actual_backend=engine,
                counts={
                    "assigned_segments": assigned_segments,
                    "clusters": cluster_count,
                    "assigned_clusters": len(assigned_cluster_ids),
                    "tracks": len(grouped),
                },
                duration_seconds=time.perf_counter() - started_at,
                details={
                    "provider": selected_provider,
                    "processed_tracks": diarizable_ids,
                    "microphone_fixed_cluster": bool(mic_timeline),
                    "text_preserved": True,
                },
            ),
        }
        recording_store.save_speaker_diarization(
            recording_id,
            {**public_summary, "tracks": tracks},
        )

        updated = dict(original)
        updated["segments"] = segments
        updated.pop("speaker_attribution", None)
        stats = dict(updated.get("stats") or {})
        stats.pop("speaker_attribution", None)
        stats.pop("recording_pipeline_cache_key", None)
        stats["speaker_diarization"] = public_summary
        stats["speaker_diarization_override"] = {
            "provider": selected_provider,
            "timestamp": time.time(),
        }
        updated["stats"] = stats
        updated["speaker_diarization"] = public_summary
        updated = apply_speaker_labels(updated)

        previous_diagnostics = [
            item
            for item in (original.get("diagnostics") or stats.get("diagnostics") or [])
            if item.get("component") != "speaker_diarization"
        ]
        updated = attach_diagnostics(updated, [*previous_diagnostics, public_summary])
        self._update_source_track_metadata(updated, assigned_by_track, engine)

        if progress_callback:
            progress_callback(
                "saving_diarization",
                90,
                {
                    "provider": selected_provider,
                    "cluster_count": cluster_count,
                    "assigned_segments": assigned_segments,
                },
            )
        return transcription_store.replace_diarization(transcription_id, updated)

    def _run_local(
        self,
        recording_store: Any,
        recording_id: str,
        tracks_by_id: dict[str, tuple[dict[str, Any], Path]],
        grouped: dict[str, list[dict[str, Any]]],
        diarizable_ids: list[str],
    ) -> dict[str, Any]:
        selected_paths = [tracks_by_id[track_id] for track_id in diarizable_ids]
        selected_results = [
            {
                "track": tracks_by_id[track_id][0],
                "result": {"segments": grouped[track_id]},
            }
            for track_id in diarizable_ids
        ]
        if not selected_paths:
            return {"status": "completed", "engine": DIARIZATION_ENGINE, "tracks": {}}
        summary = self.local.process(
            recording_store,
            recording_id,
            selected_paths,
            selected_results,
            force=True,
        )
        if summary.get("status") != "completed":
            raise RuntimeError(summary.get("error") or "Local speaker diarization failed")
        return summary

    def _run_speechmatics(
        self,
        recording_id: str,
        tracks_by_id: dict[str, tuple[dict[str, Any], Path]],
        grouped: dict[str, list[dict[str, Any]]],
        diarizable_ids: list[str],
        *,
        language: str | None,
        region: str | None,
        model: str | None,
        progress_callback: Callable[[str, int, dict[str, Any] | None], None] | None,
    ) -> dict[str, Any]:
        settings = load_settings()
        options = speechmatics_options_from_settings(
            settings,
            model=model,
            region=region,
            diarization="speaker",
        )
        minimum_overlap = float(settings.get("speaker_diarization_minimum_overlap", 0.25))
        tracks: dict[str, Any] = {}
        assigned = 0
        total = max(1, len(diarizable_ids))
        for index, track_id in enumerate(diarizable_ids, start=1):
            if progress_callback:
                progress_callback(
                    "diarizing_system",
                    15 + int(((index - 1) / total) * 65),
                    {
                        "provider": ASR_PROVIDER_SPEECHMATICS,
                        "track_id": track_id,
                        "track_index": index,
                        "track_count": len(diarizable_ids),
                    },
                )
            _track, audio_path = tracks_by_id[track_id]
            result = self.speechmatics.transcribe(ASRRequest(
                audio_path=audio_path,
                model=str(options.get("speechmatics_model") or DEFAULT_SPEECHMATICS_MODEL),
                language=language,
                provider=ASR_PROVIDER_SPEECHMATICS,
                provider_options=options,
            ))
            timeline = [
                {
                    "speaker": str(segment["provider_speaker"]),
                    "start": float(segment.get("start") or 0.0),
                    "end": float(segment.get("end") or segment.get("start") or 0.0),
                }
                for segment in (result.get("segments") or [])
                if segment.get("provider_speaker")
            ]
            tracks[track_id] = {
                "segments": timeline,
                "metadata": result.get("metadata") or {},
            }
            assigned += self.local.assign_segments(
                {"segments": grouped[track_id]},
                track_id,
                timeline,
                minimum_overlap,
            )
        return {
            "status": "completed",
            "engine": SPEECHMATICS_DIARIZATION_ENGINE,
            "assigned_segments": assigned,
            "tracks": tracks,
            "recording_id": recording_id,
        }

    @staticmethod
    def _update_source_track_metadata(
        payload: dict[str, Any],
        assigned_by_track: dict[str, int],
        engine: str,
    ) -> None:
        for track in payload.get("source_tracks") or []:
            track_id = str(track.get("id") or "")
            metadata = dict(track.get("transcription_metadata") or {})
            metadata["speaker_diarization"] = {
                "engine": engine,
                "assigned_segments": assigned_by_track.get(track_id, 0),
                "rerun": True,
            }
            track["transcription_metadata"] = metadata
