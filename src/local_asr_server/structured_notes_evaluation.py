from __future__ import annotations

import re
from typing import Any

from local_asr_server.structured_notes import (
    STRUCTURED_NOTES_SCHEMA_ID,
    STRUCTURED_NOTES_SCHEMA_VERSION,
)


DEFAULT_RUBRIC_THRESHOLDS = {
    "factual_support": 0.95,
    "action_recall": 0.90,
    "decision_recall": 0.90,
    "attribution": 0.90,
}


def _normalized_text(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _contains(candidate: str, expectation: Any) -> bool:
    if isinstance(expectation, str):
        phrases = [expectation]
    elif isinstance(expectation, list):
        phrases = expectation
    else:
        return False
    normalized_candidate = _normalized_text(candidate)
    return all(_normalized_text(phrase) in normalized_candidate for phrase in phrases if _normalized_text(phrase))


def _source_ids(item: dict[str, Any]) -> set[str]:
    return {
        str(ref.get("segment_id"))
        for ref in item.get("source_refs") or []
        if isinstance(ref, dict) and ref.get("segment_id") is not None
    }


def _recall_and_attribution(
    candidates: list[dict[str, Any]],
    expected: list[dict[str, Any]],
) -> tuple[float, int, int]:
    if not expected:
        return 1.0, 0, 0
    matched = 0
    attributed = 0
    for expectation in expected:
        candidate = next(
            (
                item
                for item in candidates
                if _contains(str(item.get("text") or ""), expectation.get("contains"))
            ),
            None,
        )
        if candidate is None:
            continue
        matched += 1
        expected_sources = {str(value) for value in expectation.get("segment_ids") or []}
        if not expected_sources or _source_ids(candidate).intersection(expected_sources):
            attributed += 1
    return matched / len(expected), matched, attributed


def evaluate_structured_notes(
    result: dict[str, Any],
    expected: dict[str, Any],
    *,
    baseline_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = result.get("schema") or {}
    schema_validity = float(
        schema.get("id") == STRUCTURED_NOTES_SCHEMA_ID
        and schema.get("version") == STRUCTURED_NOTES_SCHEMA_VERSION
        and isinstance(result.get("generated"), dict)
    )
    generated = result.get("generated") or {}
    summary = generated.get("summary") or {}
    actions = list(generated.get("actions") or [])
    decisions = list(generated.get("decisions") or [])
    risks = list(generated.get("risks") or [])

    support_items: list[dict[str, Any]] = []
    if summary.get("text"):
        support_items.append(summary)
    support_items.extend(actions)
    support_items.extend(decisions)
    support_items.extend(risks)
    supported = sum(1 for item in support_items if _source_ids(item))
    factual_support = supported / len(support_items) if support_items else 1.0

    action_recall, action_matches, action_attributed = _recall_and_attribution(
        actions,
        list(expected.get("actions") or []),
    )
    decision_recall, decision_matches, decision_attributed = _recall_and_attribution(
        decisions,
        list(expected.get("decisions") or []),
    )
    risk_recall, risk_matches, risk_attributed = _recall_and_attribution(
        risks,
        list(expected.get("risks") or []),
    )
    matched_total = action_matches + decision_matches + risk_matches
    attribution = (
        (action_attributed + decision_attributed + risk_attributed) / matched_total
        if matched_total
        else 1.0
    )

    metrics = dict(result.get("metrics") or {})
    baseline = dict(baseline_metrics or {})
    candidate_inferences = metrics.get("inference_count")
    baseline_inferences = baseline.get("inference_count")
    candidate_tokens = metrics.get("estimated_input_tokens")
    baseline_tokens = baseline.get("estimated_input_tokens")
    inference_improved = (
        isinstance(candidate_inferences, int)
        and isinstance(baseline_inferences, int)
        and candidate_inferences < baseline_inferences
    ) if baseline else None
    token_ratio = (
        float(candidate_tokens) / float(baseline_tokens)
        if isinstance(candidate_tokens, int) and isinstance(baseline_tokens, int) and baseline_tokens > 0
        else None
    )
    candidate_peak = metrics.get("peak_rss_bytes")
    baseline_peak = baseline.get("peak_rss_bytes")
    peak_memory_ratio = (
        float(candidate_peak) / float(baseline_peak)
        if isinstance(candidate_peak, int) and isinstance(baseline_peak, int) and baseline_peak > 0
        else None
    )

    return {
        "schema_validity": schema_validity,
        "factual_support": factual_support,
        "action_recall": action_recall,
        "decision_recall": decision_recall,
        "risk_recall": risk_recall,
        "attribution": attribution,
        "latency_ms": metrics.get("latency_ms"),
        "inference_count": candidate_inferences,
        "estimated_input_tokens": candidate_tokens,
        "peak_rss_bytes": candidate_peak,
        "baseline_inference_count": baseline_inferences,
        "baseline_estimated_input_tokens": baseline_tokens,
        "inference_count_improved": inference_improved,
        "estimated_input_token_ratio": token_ratio,
        "peak_memory_ratio": peak_memory_ratio,
        "peak_memory_assessment": "measured" if peak_memory_ratio is not None else "unknown",
    }


def passes_default_gate(
    report: dict[str, Any],
    *,
    thresholds: dict[str, float] | None = None,
) -> bool:
    required = {**DEFAULT_RUBRIC_THRESHOLDS, **(thresholds or {})}
    if report.get("schema_validity") != 1.0:
        return False
    for metric, minimum in required.items():
        if float(report.get(metric, 0.0)) < minimum:
            return False
    if report.get("inference_count_improved") is not True:
        return False
    token_ratio = report.get("estimated_input_token_ratio")
    if token_ratio is not None and float(token_ratio) > 1.25:
        return False
    peak_ratio = report.get("peak_memory_ratio")
    if peak_ratio is not None and float(peak_ratio) > 1.10:
        return False
    return True
