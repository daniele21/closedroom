from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any


VAD_BACKEND_BENCHMARK_SCHEMA_VERSION = 1


def _intervals(windows: list[dict[str, float]]) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for item in windows:
        try:
            start = max(0.0, float(item.get("start") or 0.0))
            end = max(start, float(item.get("end") or start))
        except (TypeError, ValueError):
            continue
        if end > start:
            intervals.append((start, end))
    intervals.sort()
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return merged


def interval_duration(windows: list[dict[str, float]]) -> float:
    return sum(end - start for start, end in _intervals(windows))


def timeline_recall(
    reference: list[dict[str, float]],
    candidate: list[dict[str, float]],
) -> float | None:
    reference_intervals = _intervals(reference)
    candidate_intervals = _intervals(candidate)
    reference_duration = sum(end - start for start, end in reference_intervals)
    if reference_duration <= 0:
        return None
    intersection = 0.0
    candidate_index = 0
    for reference_start, reference_end in reference_intervals:
        while (
            candidate_index < len(candidate_intervals)
            and candidate_intervals[candidate_index][1] <= reference_start
        ):
            candidate_index += 1
        check_index = candidate_index
        while check_index < len(candidate_intervals):
            candidate_start, candidate_end = candidate_intervals[check_index]
            if candidate_start >= reference_end:
                break
            intersection += max(
                0.0,
                min(reference_end, candidate_end) - max(reference_start, candidate_start),
            )
            if candidate_end >= reference_end:
                break
            check_index += 1
    return min(1.0, intersection / reference_duration)


def reference_segment_windows(audio_path: Path) -> list[dict[str, float]]:
    """Load only timing/track metadata from an existing local transcript for quality proxying."""
    transcript_path = audio_path.parent / "transcript.json"
    if not transcript_path.is_file():
        return []
    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    track_id = "mixed" if audio_path.stem == "recording" else audio_path.stem
    windows: list[dict[str, float]] = []
    for segment in payload.get("segments") or []:
        segment_track = str(segment.get("track_id") or "")
        if segment_track and segment_track != track_id:
            continue
        if not segment_track and track_id != "mixed":
            continue
        try:
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or start)
        except (TypeError, ValueError):
            continue
        if end > start:
            windows.append({"start": start, "end": end})
    return windows


def timeline_jaccard(
    left: list[dict[str, float]],
    right: list[dict[str, float]],
) -> float | None:
    left_intervals = _intervals(left)
    right_intervals = _intervals(right)
    if not left_intervals and not right_intervals:
        return 1.0
    if not left_intervals or not right_intervals:
        return 0.0

    left_index = 0
    right_index = 0
    intersection = 0.0
    while left_index < len(left_intervals) and right_index < len(right_intervals):
        left_start, left_end = left_intervals[left_index]
        right_start, right_end = right_intervals[right_index]
        intersection += max(0.0, min(left_end, right_end) - max(left_start, right_start))
        if left_end <= right_end:
            left_index += 1
        else:
            right_index += 1

    left_duration = sum(end - start for start, end in left_intervals)
    right_duration = sum(end - start for start, end in right_intervals)
    union = left_duration + right_duration - intersection
    return intersection / union if union > 0 else None


def summarize_backend_runs(runs: list[dict[str, Any]], *, duration_seconds: float) -> dict[str, Any]:
    if not runs:
        raise ValueError("At least one backend run is required")
    wall_times = [float(run["wall_seconds"]) for run in runs]
    speech_seconds = [float(run["speech_seconds"]) for run in runs]
    window_counts = [int(run["window_count"]) for run in runs]
    duration = max(0.0, float(duration_seconds))
    median_speech = median(speech_seconds)
    return {
        "repeat_count": len(runs),
        "median_wall_seconds": round(median(wall_times), 6),
        "median_speech_seconds": round(median_speech, 3),
        "median_speech_ratio": round(median_speech / duration, 4) if duration > 0 else None,
        "median_window_count": round(median(window_counts), 2),
    }


def build_case_report(
    *,
    index: int,
    bytes_total: int,
    duration_seconds: float,
    canonical_wav: bool,
    silero_runs: list[dict[str, Any]],
    rms_runs: list[dict[str, Any]],
    silero_windows: list[dict[str, float]],
    rms_windows: list[dict[str, float]],
    reference_windows: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    silero = summarize_backend_runs(silero_runs, duration_seconds=duration_seconds)
    rms = summarize_backend_runs(rms_runs, duration_seconds=duration_seconds)
    jaccard = timeline_jaccard(silero_windows, rms_windows)
    reference_windows = reference_windows or []
    silero_reference_recall = timeline_recall(reference_windows, silero_windows)
    rms_reference_recall = timeline_recall(reference_windows, rms_windows)
    silero_wall = float(silero["median_wall_seconds"])
    rms_wall = float(rms["median_wall_seconds"])
    return {
        "index": index,
        "bytes": max(0, int(bytes_total)),
        "duration_seconds": round(max(0.0, duration_seconds), 3),
        "canonical_wav": bool(canonical_wav),
        "silero": silero,
        "energy_rms": rms,
        "comparison": {
            "timeline_jaccard": round(jaccard, 4) if jaccard is not None else None,
            "rms_to_silero_wall_ratio": round(rms_wall / silero_wall, 4) if silero_wall > 0 else None,
            "speech_ratio_delta_rms_minus_silero": (
                round(float(rms["median_speech_ratio"]) - float(silero["median_speech_ratio"]), 4)
                if rms["median_speech_ratio"] is not None and silero["median_speech_ratio"] is not None
                else None
            ),
            "reference_segment_seconds": round(interval_duration(reference_windows), 3),
            "silero_reference_speech_recall": (
                round(silero_reference_recall, 4) if silero_reference_recall is not None else None
            ),
            "rms_reference_speech_recall": (
                round(rms_reference_recall, 4) if rms_reference_recall is not None else None
            ),
            "reference_recall_delta_rms_minus_silero": (
                round(rms_reference_recall - silero_reference_recall, 4)
                if rms_reference_recall is not None and silero_reference_recall is not None
                else None
            ),
        },
    }


def build_benchmark_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        raise ValueError("At least one audio case is required")
    jaccards = [
        float(case["comparison"]["timeline_jaccard"])
        for case in cases
        if case.get("comparison", {}).get("timeline_jaccard") is not None
    ]
    ratios = [
        float(case["comparison"]["rms_to_silero_wall_ratio"])
        for case in cases
        if case.get("comparison", {}).get("rms_to_silero_wall_ratio") is not None
    ]
    reference_recalls = [
        float(case["comparison"]["rms_reference_speech_recall"])
        for case in cases
        if case.get("comparison", {}).get("rms_reference_speech_recall") is not None
    ]
    return {
        "schema_version": VAD_BACKEND_BENCHMARK_SCHEMA_VERSION,
        "benchmark": "silero_vad_vs_energy_rms",
        "privacy": {
            "retains_audio": False,
            "retains_transcript": False,
            "retains_paths_or_filenames": False,
        },
        "case_count": len(cases),
        "summary": {
            "median_timeline_jaccard": round(median(jaccards), 4) if jaccards else None,
            "median_rms_to_silero_wall_ratio": round(median(ratios), 4) if ratios else None,
            "median_rms_reference_speech_recall": (
                round(median(reference_recalls), 4) if reference_recalls else None
            ),
        },
        "cases": cases,
        "decision_policy": {
            "automatic_recommendation": False,
            "reason": (
                "Backend removal requires representative meeting quality evidence; "
                "agreement and timing alone are not ground truth."
            ),
        },
    }


_FINALIZED_RECORDING_STATUSES = {"recorded", "completed"}


def discover_finalized_recording_tracks(root: Path, *, recording_limit: int) -> list[Path]:
    """Return audio tracks from the newest finalized recordings without mutating store state."""
    if recording_limit < 1:
        raise ValueError("recording_limit must be >= 1")
    root = root.expanduser().resolve()
    candidates: list[tuple[str, list[Path]]] = []
    for metadata_path in root.glob("*/*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(metadata.get("status") or "") not in _FINALIZED_RECORDING_STATUSES:
            continue

        tracks = list(metadata.get("audio_tracks") or [])
        selected = [
            track
            for track in tracks
            if str(track.get("source") or "") in {"mic", "system"}
        ]
        if not selected and tracks:
            primary = next((track for track in tracks if track.get("primary")), tracks[0])
            selected = [primary]

        session_dir = metadata_path.parent
        audio_paths: list[Path] = []
        for track in selected:
            track_id = str(track.get("id") or "mixed")
            extension = str(track.get("extension") or metadata.get("extension") or ".wav")
            stem = "recording" if track_id == "mixed" else track_id
            audio_path = session_dir / f"{stem}{extension}"
            if audio_path.is_file():
                audio_paths.append(audio_path)
        if audio_paths:
            candidates.append((str(metadata.get("created_at") or ""), audio_paths))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [
        path
        for _created_at, paths in candidates[:recording_limit]
        for path in paths
    ]
