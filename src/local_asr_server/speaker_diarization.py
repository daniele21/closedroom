from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess
from typing import Any, Callable

from local_asr_server.settings import load_settings
from local_asr_server.paths import get_models_dir
from local_asr_server.runtime.leases import ModelRuntimeLeaseManager
from local_asr_server.speaker_diarization_helper.compile import get_helper_binary
from local_asr_server.diagnostics import diagnostic


logger = logging.getLogger("uvicorn.error")
DIARIZATION_ENGINE = "fluidaudio-community-1"


def clusters_from_timeline(track_id: str, timeline: list[dict[str, Any]]) -> list[str]:
    """Return every detected cluster in first-seen order, namespaced by track."""
    clusters: list[str] = []
    prefix = f"{track_id}:"
    for segment in sorted(
        timeline or [],
        key=lambda item: (float(item.get("start") or 0.0), float(item.get("end") or 0.0)),
    ):
        speaker = str(segment.get("speaker") or "").strip()
        if not speaker:
            continue
        cluster = speaker if speaker.startswith(prefix) else f"{prefix}{speaker}"
        if cluster not in clusters:
            clusters.append(cluster)
    return clusters


def assigned_clusters(segments: list[dict[str, Any]]) -> list[str]:
    """Return clusters that could be attached to preserved transcript segments."""
    clusters: list[str] = []
    for segment in segments or []:
        cluster = str(segment.get("provider_speaker") or "").strip()
        if cluster and cluster not in clusters:
            clusters.append(cluster)
    return clusters


class LocalSpeakerDiarizationService:
    """Add local FluidAudio speaker clusters to ASR segments post-meeting."""

    def __init__(
        self,
        runner: Callable[[dict[str, Path]], dict[str, Any]] | None = None,
        *,
        model_phases: ModelRuntimeLeaseManager | None = None,
    ) -> None:
        self._runner = runner or self._run_helper
        self.model_phases = model_phases or ModelRuntimeLeaseManager()

    def process(
        self,
        store: Any,
        recording_id: str,
        track_paths: list[tuple[dict[str, Any], Path]],
        track_results: list[dict[str, Any]],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        settings = load_settings()
        if not force and not settings.get("speaker_diarization_enabled", False):
            return {
                "status": "disabled",
                "engine": DIARIZATION_ENGINE,
                **diagnostic("speaker_diarization", "disabled", requested_backend=DIARIZATION_ENGINE),
            }
        try:
            inputs = {str(track["id"]): path for track, path in track_paths}
            model_path = get_models_dir() / "fluidaudio-speaker-diarization"
            result = self.diarize_paths(inputs)
            tracks = result.get("tracks") or {}
            minimum_overlap = float(settings.get("speaker_diarization_minimum_overlap", 0.25))
            assigned = 0
            for item in track_results:
                track_id = str(item["track"]["id"])
                diarized = (tracks.get(track_id) or {}).get("segments") or []
                assigned += self.assign_segments(item["result"], track_id, diarized, minimum_overlap)
            clusters_by_track = {
                track_id: clusters_from_timeline(
                    track_id,
                    list((track_payload or {}).get("segments") or []),
                )
                for track_id, track_payload in tracks.items()
            }
            assigned_cluster_set = {
                cluster
                for item in track_results
                for cluster in assigned_clusters(item["result"].get("segments") or [])
            }
            unassigned_clusters_by_track = {
                track_id: [
                    cluster for cluster in clusters if cluster not in assigned_cluster_set
                ]
                for track_id, clusters in clusters_by_track.items()
            }
            summary = {
                "status": "completed",
                "engine": result.get("engine") or DIARIZATION_ENGINE,
                "assigned_segments": assigned,
                "cluster_count": sum(len(items) for items in clusters_by_track.values()),
                "clusters_by_track": clusters_by_track,
                "assigned_cluster_count": len(assigned_cluster_set),
                "unassigned_clusters_by_track": unassigned_clusters_by_track,
                "model_path": str(model_path),
                "tracks": tracks,
                **diagnostic(
                    "speaker_diarization",
                    "completed",
                    requested_backend=DIARIZATION_ENGINE,
                    actual_backend=result.get("engine") or DIARIZATION_ENGINE,
                    counts={
                        "assigned_segments": assigned,
                        "clusters": sum(len(items) for items in clusters_by_track.values()),
                        "assigned_clusters": len(assigned_cluster_set),
                        "tracks": len(tracks),
                    },
                    details={"model_path": str(model_path)},
                ),
            }
            store.save_speaker_diarization(recording_id, summary)
            return summary
        except Exception as exc:
            logger.warning("[Speaker diarization] Recording %s skipped: %s", recording_id, exc)
            summary = {
                "status": "failed",
                "engine": DIARIZATION_ENGINE,
                **diagnostic(
                    "speaker_diarization",
                    "failed",
                    requested_backend=DIARIZATION_ENGINE,
                    error=str(exc),
                    details={"model_path": str(model_path)},
                ),
            }
            store.save_speaker_diarization(recording_id, summary)
            return summary

    def diarize_paths(self, inputs: dict[str, Path]) -> dict[str, Any]:
        """Run FluidAudio for explicit audio paths without requiring persistence."""
        self.model_phases.acquire_lease("diarization")
        try:
            return self._runner(inputs)
        finally:
            self.model_phases.release_lease("diarization")

    @staticmethod
    def assign_segments(
        result: dict[str, Any],
        track_id: str,
        diarized: list[dict[str, Any]],
        minimum_overlap: float,
    ) -> int:
        assigned = 0
        for segment in result.get("segments", []) or []:
            if segment.get("provider_speaker"):
                continue
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or start)
            duration = max(0.001, end - start)
            best: tuple[float, str] | None = None
            for candidate in diarized:
                overlap = max(0.0, min(end, float(candidate["end"])) - max(start, float(candidate["start"])))
                if best is None or overlap > best[0]:
                    best = (overlap, str(candidate["speaker"]))
            if best and best[0] / duration >= minimum_overlap:
                prefix = f"{track_id}:"
                segment["provider_speaker"] = (
                    best[1] if best[1].startswith(prefix) else f"{prefix}{best[1]}"
                )
                assigned += 1
        result.setdefault("metadata", {})["speaker_diarization"] = {
            "engine": DIARIZATION_ENGINE,
            "assigned_segments": assigned,
        }
        return assigned

    @staticmethod
    def _run_helper(inputs: dict[str, Path]) -> dict[str, Any]:
        models_dir = get_models_dir() / "fluidaudio-speaker-diarization"
        models_dir.mkdir(parents=True, exist_ok=True)
        command = [get_helper_binary(), "process", "--models-dir", str(models_dir)]
        for track_id, path in inputs.items():
            command.extend(["--input", f"{track_id}={path}"])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "FluidAudio helper failed")
        return json.loads(completed.stdout)
