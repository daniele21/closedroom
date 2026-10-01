from __future__ import annotations

from difflib import SequenceMatcher
from statistics import median
from typing import Any

from local_asr_server.transcription_quality import normalize_text


AUDIO_STRATEGY_BENCHMARK_SCHEMA_VERSION = 1
ATTRIBUTABLE_SOURCES = {"mic", "system"}


def _segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (payload.get("segments") or []) if isinstance(item, dict)]


def _tokens(payload: dict[str, Any]) -> list[str]:
    segments = _segments(payload)
    text = " ".join(str(item.get("text") or "") for item in segments) if segments else str(payload.get("text") or "")
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


def _merged_intervals(payload: dict[str, Any]) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for segment in _segments(payload):
        try:
            start = max(0.0, float(segment.get("start") or 0.0))
            end = max(start, float(segment.get("end") or start))
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


def _duration(intervals: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in intervals)


def _intersection_duration(
    left: list[tuple[float, float]],
    right: list[tuple[float, float]],
) -> float:
    total = 0.0
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_start, left_end = left[left_index]
        right_start, right_end = right[right_index]
        total += max(0.0, min(left_end, right_end) - max(left_start, right_start))
        if left_end <= right_end:
            left_index += 1
        else:
            right_index += 1
    return total


def transcript_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Word-order similarity without retaining transcript content in the report."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return SequenceMatcher(None, left_tokens, right_tokens, autojunk=False).ratio()


def timeline_jaccard(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    """Jaccard overlap of speech-bearing segment intervals on the meeting timeline."""
    left_intervals = _merged_intervals(left)
    right_intervals = _merged_intervals(right)
    if not left_intervals and not right_intervals:
        return 1.0
    if not left_intervals or not right_intervals:
        return 0.0
    intersection = _intersection_duration(left_intervals, right_intervals)
    union = _duration(left_intervals) + _duration(right_intervals) - intersection
    return intersection / union if union > 0 else None


def strategy_metrics(
    payload: dict[str, Any],
    *,
    wall_seconds: float,
    asr_audio_seconds: float,
) -> dict[str, Any]:
    segments = _segments(payload)
    sources = []
    attributed = 0
    for segment in segments:
        source = str(segment.get("source") or segment.get("track_id") or "").strip()
        if source:
            sources.append(source)
        if source in ATTRIBUTABLE_SOURCES:
            attributed += 1
    tokens = _tokens(payload)
    return {
        "wall_seconds": round(max(0.0, wall_seconds), 4),
        "asr_audio_seconds": round(max(0.0, asr_audio_seconds), 3),
        "word_count": len(tokens),
        "segment_count": len(segments),
        "attributed_segment_ratio": round(attributed / len(segments), 4) if segments else None,
        "source_count": len(set(sources)),
        "sources": sorted(set(sources)),
    }


def build_run_report(
    *,
    dual_payload: dict[str, Any],
    mixed_payload: dict[str, Any],
    dual_wall_seconds: float,
    mixed_wall_seconds: float,
    dual_audio_seconds: float,
    mixed_audio_seconds: float,
    order: str,
) -> dict[str, Any]:
    dual = strategy_metrics(
        dual_payload,
        wall_seconds=dual_wall_seconds,
        asr_audio_seconds=dual_audio_seconds,
    )
    mixed = strategy_metrics(
        mixed_payload,
        wall_seconds=mixed_wall_seconds,
        asr_audio_seconds=mixed_audio_seconds,
    )
    return {
        "order": order,
        "dual_track": dual,
        "mixed_track": mixed,
        "comparison": {
            "dual_to_mixed_audio_ratio": round(dual_audio_seconds / mixed_audio_seconds, 4)
            if mixed_audio_seconds > 0
            else None,
            "dual_to_mixed_wall_ratio": round(dual_wall_seconds / mixed_wall_seconds, 4)
            if mixed_wall_seconds > 0
            else None,
            "transcript_similarity": round(transcript_similarity(dual_payload, mixed_payload), 4),
            "timeline_jaccard": (
                round(value, 4)
                if (value := timeline_jaccard(dual_payload, mixed_payload)) is not None
                else None
            ),
            "attribution_ratio_delta": (
                round((dual["attributed_segment_ratio"] or 0.0) - (mixed["attributed_segment_ratio"] or 0.0), 4)
                if dual["attributed_segment_ratio"] is not None or mixed["attributed_segment_ratio"] is not None
                else None
            ),
        },
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        raise ValueError("At least one benchmark run is required")

    def values(path: tuple[str, ...]) -> list[float]:
        collected: list[float] = []
        for run in runs:
            value: Any = run
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            if isinstance(value, (int, float)):
                collected.append(float(value))
        return collected

    def median_or_none(path: tuple[str, ...]) -> float | None:
        collected = values(path)
        return round(median(collected), 4) if collected else None

    return {
        "repeat_count": len(runs),
        "median_dual_wall_seconds": median_or_none(("dual_track", "wall_seconds")),
        "median_mixed_wall_seconds": median_or_none(("mixed_track", "wall_seconds")),
        "median_dual_to_mixed_wall_ratio": median_or_none(("comparison", "dual_to_mixed_wall_ratio")),
        "dual_to_mixed_audio_ratio": median_or_none(("comparison", "dual_to_mixed_audio_ratio")),
        "median_transcript_similarity": median_or_none(("comparison", "transcript_similarity")),
        "median_timeline_jaccard": median_or_none(("comparison", "timeline_jaccard")),
        "median_attribution_ratio_delta": median_or_none(("comparison", "attribution_ratio_delta")),
    }


def build_benchmark_report(
    *,
    runs: list[dict[str, Any]],
    input_summary: dict[str, Any],
    model: str,
    language: str | None,
) -> dict[str, Any]:
    """Build a privacy-safe evidence artifact. No transcript text is retained."""
    return {
        "schema_version": AUDIO_STRATEGY_BENCHMARK_SCHEMA_VERSION,
        "benchmark": "dual_track_vs_mixed_asr",
        "model": model,
        "language": language,
        "input": input_summary,
        "summary": summarize_runs(runs),
        "runs": runs,
        "decision_policy": {
            "automatic_recommendation": False,
            "reason": "Audio ownership changes require representative quality, attribution, and compute evidence.",
        },
    }
