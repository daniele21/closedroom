from __future__ import annotations

from typing import Any


def _time_label(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def apply_speaker_labels(
    payload: dict[str, Any],
    manual_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve diarization clusters to names or stable Speaker N fallbacks."""
    segments = payload.get("segments", []) or []

    # Ensure every segment has a stable provider_speaker cluster identifier
    for segment in segments:
        cluster = segment.get("provider_speaker") or segment.get("speaker_label")
        if cluster and not segment.get("provider_speaker"):
            segment["provider_speaker"] = cluster

    existing = (
        payload.get("speaker_attribution")
        or payload.get("stats", {}).get("speaker_attribution")
        or {}
    )
    existing_mappings = {
        str(item.get("speaker_cluster")): dict(item)
        for item in existing.get("mappings", []) or []
        if item.get("speaker_cluster")
    }
    manual = {
        str(cluster): str(name).strip()[:120]
        for cluster, name in (manual_names or {}).items()
        if str(name).strip()
    }
    clusters: list[str] = []
    diarization = (
        payload.get("speaker_diarization")
        or payload.get("stats", {}).get("speaker_diarization")
        or {}
    )
    for track_clusters in (diarization.get("clusters_by_track") or {}).values():
        for cluster in track_clusters or []:
            value = str(cluster)
            if value and value not in clusters:
                clusters.append(value)
    known_labels: dict[str, str] = {}
    segment_counts: dict[str, int] = {}
    for segment in sorted(segments, key=lambda item: (float(item.get("start") or 0), int(item.get("id") or 0))):
        cluster = segment.get("provider_speaker") or segment.get("speaker_label")
        if cluster and str(cluster) not in clusters:
            clusters.append(str(cluster))
        if cluster:
            segment_counts[str(cluster)] = segment_counts.get(str(cluster), 0) + 1
        if cluster and segment.get("speaker_label"):
            label = str(segment["speaker_label"])
            if not str(cluster).startswith("Speaker "):
                known_labels[str(cluster)] = label

    mappings = []
    labels: dict[str, str] = {}
    for index, cluster in enumerate(clusters, start=1):
        previous = existing_mappings.get(cluster, {})
        accepted_name = previous.get("display_name") if previous.get("status") == "accepted" else None
        display_name = manual.get(cluster) or accepted_name or known_labels.get(cluster) or f"Speaker {index}"
        source = "manual" if cluster in manual else previous.get("source") or (
            "visual" if accepted_name else "diarization"
        )
        status = "accepted" if cluster in manual or accepted_name else "unassigned"
        labels[cluster] = display_name
        mappings.append({
            **previous,
            "speaker_cluster": cluster,
            "display_name": display_name,
            "status": status,
            "source": source,
            "transcript_segment_count": segment_counts.get(cluster, 0),
        })

    text_lines = []
    for segment in segments:
        cluster = segment.get("provider_speaker") or segment.get("speaker_label")
        if cluster and str(cluster) in labels:
            label = labels[str(cluster)]
            segment["speaker_name"] = label
            segment["speaker_label"] = label
        label = segment.get("speaker_name") or segment.get("speaker_label") or segment.get("source") or "Audio"
        text = (segment.get("text") or "").strip()
        if text:
            text_lines.append(f"[{_time_label(float(segment.get('start') or 0))}] {label}: {text}")

    attribution = {
        **existing,
        "source": "manual" if manual else existing.get("source") or "diarization",
        "mappings": mappings,
    }
    # Speaker labeling is allowed to rebuild text only when there are transcript
    # segments to label. Text-only/imported transcriptions may legitimately have
    # no segments; replacing their canonical text with an empty reconstruction
    # would be destructive and breaks merge/export workflows.
    if segments and not payload.get("stats", {}).get("review_preserve_canonical_text"):
        payload["text"] = "\n".join(text_lines)
    payload["speaker_attribution"] = attribution
    payload.setdefault("stats", {})["speaker_attribution"] = attribution
    return payload
