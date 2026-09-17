from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any

from local_asr_server.visual_intelligence.contracts import (
    FrameCandidate,
    VisualRoutingConfig,
    VisualTask,
    VisualTrigger,
)
from local_asr_server.visual_intelligence.signatures import (
    FrameSignature,
    calculate_signature,
    get_or_calculate_signature,
    hamming_distance,
    participant_tile_changed,
)


class TaskAwareFrameRouter:
    def __init__(self, config: VisualRoutingConfig) -> None:
        self.config = config

    def route(
        self,
        frames: list[dict[str, Any]],
        segments: list[dict[str, Any]],
    ) -> tuple[list[FrameCandidate], dict[str, Any]]:
        if not frames:
            return [], self._summary(0, [], uncapped_candidate_count=0)
        signatures: dict[int, FrameSignature] = {}

        def get_sig(frame: dict[str, Any], calculate_tiles: bool = False) -> FrameSignature:
            return get_or_calculate_signature(
                Path(frame["path"]),
                signatures,
                int(frame["sequence"]),
                calculate_tiles=calculate_tiles,
                participant_rows=self.config.participant_grid_rows,
                participant_columns=self.config.participant_grid_columns,
            )

        candidates: list[FrameCandidate] = []
        candidates.extend(self._speaker_candidates(frames, segments, get_sig))
        candidates.extend(self._state_candidates(frames, get_sig))
        candidates.extend(self._shared_candidates(frames, get_sig))
        unique: dict[tuple[int, VisualTask], FrameCandidate] = {}
        for candidate in candidates:
            unique.setdefault((candidate.sequence, candidate.task), candidate)
        ordered = sorted(unique.values(), key=lambda item: (item.timestamp, item.task.value))
        uncapped_candidate_count = len(ordered)
        bounded = self._apply_candidate_budget(ordered, self.config.max_candidates)
        return bounded, self._summary(
            len(frames), bounded, uncapped_candidate_count=uncapped_candidate_count,
        )

    @staticmethod
    def _apply_candidate_budget(
        candidates: list[FrameCandidate],
        max_candidates: int,
    ) -> list[FrameCandidate]:
        """Bound VLM work while preserving deterministic coverage across the full meeting timeline."""
        if max_candidates < 1:
            raise ValueError("max_candidates must be at least 1")
        if len(candidates) <= max_candidates:
            return candidates
        if max_candidates == 1:
            return [candidates[0]]
        last_index = len(candidates) - 1
        return [
            candidates[round(index * last_index / (max_candidates - 1))]
            for index in range(max_candidates)
        ]

    def _speaker_candidates(self, frames, segments, signature) -> list[FrameCandidate]:
        selected: list[FrameCandidate] = [self._candidate(frames[0], VisualTask.MEETING_UI, VisualTrigger.FIRST_FRAME)]
        diarized_targets = []
        frame_indexes = {int(frame["sequence"]): index for index, frame in enumerate(frames)}
        frame_timestamps = [float(f["timestamp"]) for f in frames]
        processed_primary_sequences: set[int] = set()
        for segment in segments:
            if not segment.get("provider_speaker") or segment.get("source") == "mic":
                continue
            target = float(segment.get("start") or 0.0) + self.config.speaker_delay_seconds
            idx = bisect.bisect_left(frame_timestamps, target)
            frame = frames[idx] if idx < len(frames) else None
            if frame:
                turn_id = str(segment.get("id") or "")
                cluster = segment.get("provider_speaker")
                selected.append(self._candidate(
                    frame, VisualTask.MEETING_UI, VisualTrigger.DIARIZATION_TURN_START,
                    diarization_turn_id=turn_id, expected_cluster=cluster
                ))
                diarized_targets.append(float(frame["timestamp"]))
                primary_sequence = int(frame["sequence"])
                if primary_sequence in processed_primary_sequences:
                    continue
                processed_primary_sequences.add(primary_sequence)
                primary_index = frame_indexes[primary_sequence]
                for follow_up in frames[primary_index + 1:]:
                    if float(follow_up["timestamp"]) - target > self.config.speaker_local_window_seconds:
                        break
                    if participant_tile_changed(
                        signature(frame, calculate_tiles=True), signature(follow_up, calculate_tiles=True),
                        dhash_distance=self.config.speaker_tile_dhash_distance,
                        color_threshold=self.config.speaker_tile_color_distance,
                    ):
                        selected.append(self._candidate(
                            follow_up, VisualTask.MEETING_UI, VisualTrigger.LOCAL_CHANGE,
                            diarization_turn_id=turn_id, expected_cluster=cluster
                        ))
                        break
        if not diarized_targets:
            last_selected = float(frames[0]["timestamp"])
            for frame in frames[1:]:
                stale = float(frame["timestamp"]) - last_selected >= self.config.speaker_heartbeat_seconds
                if stale:
                    selected.append(self._candidate(frame, VisualTask.MEETING_UI, VisualTrigger.HEARTBEAT))
                    last_selected = float(frame["timestamp"])
        return selected

    def _state_candidates(self, frames, signature) -> list[FrameCandidate]:
        selected = [self._candidate(frames[0], VisualTask.MEETING_STATE, VisualTrigger.FIRST_FRAME)]
        previous = frames[0]
        last_selected = float(frames[0]["timestamp"])
        for frame in frames[1:]:
            current_signature = signature(frame, calculate_tiles=False)
            previous_signature = signature(previous, calculate_tiles=False)
            changed_grids = sum(
                hamming_distance(left, right) > self.config.structural_dhash_distance
                for left, right in zip(current_signature.grid_hashes, previous_signature.grid_hashes)
            )
            changed = (
                hamming_distance(current_signature.global_dhash, previous_signature.global_dhash)
                > self.config.structural_dhash_distance
                and changed_grids >= 2
            )
            stale = float(frame["timestamp"]) - last_selected >= self.config.meeting_state_heartbeat_seconds
            if changed or stale:
                selected.append(self._candidate(
                    frame,
                    VisualTask.MEETING_STATE,
                    VisualTrigger.STRUCTURAL_CHANGE if changed else VisualTrigger.HEARTBEAT,
                ))
                last_selected = float(frame["timestamp"])
            previous = frame
        return selected

    def _shared_candidates(self, frames, signature) -> list[FrameCandidate]:
        selected = [self._candidate(frames[0], VisualTask.SHARED_CONTENT, VisualTrigger.FIRST_FRAME, shared=True)]
        previous = frames[0]
        pending = None
        last_selected = float(frames[0]["timestamp"])
        for frame in frames[1:]:
            changed = hamming_distance(
                signature(frame, calculate_tiles=False).shared_roi_hash,
                signature(previous, calculate_tiles=False).shared_roi_hash,
            ) > self.config.shared_roi_dhash_distance
            if changed:
                pending = frame
            elif pending and float(frame["timestamp"]) - float(pending["timestamp"]) >= self.config.shared_content_stabilization_seconds:
                selected.append(self._candidate(frame, VisualTask.SHARED_CONTENT, VisualTrigger.SHARED_ROI_CHANGE, shared=True))
                last_selected = float(frame["timestamp"])
                pending = None
            elif float(frame["timestamp"]) - last_selected >= self.config.shared_content_heartbeat_seconds:
                selected.append(self._candidate(frame, VisualTask.SHARED_CONTENT, VisualTrigger.HEARTBEAT, shared=True))
                last_selected = float(frame["timestamp"])
            previous = frame
        return selected

    def _candidate(
        self, frame, task, trigger, *, shared=False, diarization_turn_id=None, expected_cluster=None
    ) -> FrameCandidate:
        roi = None
        roi_source = None
        roi_confidence = None
        roi_fallback = False
        if shared:
            roi = self.config.shared_content_roi
            valid = (
                len(roi) == 4
                and 0.0 <= roi[0] < roi[2] <= 1.0
                and 0.0 <= roi[1] < roi[3] <= 1.0
            )
            if valid:
                roi_source = "generic_meeting_content"
                roi_confidence = self.config.shared_content_roi_confidence
            else:
                roi = (0.0, 0.0, 1.0, 1.0)
                roi_source = "full_frame_fallback"
                roi_confidence = 0.0
                roi_fallback = True
        return FrameCandidate(
            sequence=int(frame["sequence"]),
            timestamp=float(frame["timestamp"]),
            task=task,
            trigger=trigger,
            roi=roi,
            roi_source=roi_source,
            roi_confidence=roi_confidence,
            roi_fallback=roi_fallback,
            diarization_turn_id=diarization_turn_id,
            expected_cluster=expected_cluster,
        )

    def _summary(
        self,
        frame_count: int,
        candidates: list[FrameCandidate],
        *,
        uncapped_candidate_count: int,
    ) -> dict[str, Any]:
        counts = {task.value: 0 for task in VisualTask}
        triggers: dict[str, int] = {}
        for candidate in candidates:
            counts[candidate.task.value] += 1
            triggers[candidate.trigger.value] = triggers.get(candidate.trigger.value, 0) + 1
        budget_rejected = max(0, uncapped_candidate_count - len(candidates))
        return {
            "schema_version": 1,
            "captured_frames": frame_count,
            "candidate_count": len(candidates),
            "uncapped_candidate_count": uncapped_candidate_count,
            "candidate_budget": self.config.max_candidates,
            "candidate_budget_applied": budget_rejected > 0,
            "budget_rejected_candidates": budget_rejected,
            "candidates_by_task": counts,
            "candidates_by_trigger": triggers,
            "rejected_task_evaluations": max(0, frame_count * len(VisualTask) - uncapped_candidate_count),
            "candidates": [candidate.public() for candidate in candidates],
        }


def legacy_candidate_sequences(
    frames: list[dict[str, Any]], *, dhash_distance: int = 2,
) -> list[int]:
    """Reproduce the v1 global-dHash inference selection for comparison only."""
    selected: list[int] = []
    last_hash = None
    for frame in frames:
        current_hash = calculate_signature(
            Path(frame["path"]), participant_rows=0, participant_columns=0,
        ).global_dhash
        if last_hash is None or hamming_distance(current_hash, last_hash) > dhash_distance:
            selected.append(int(frame["sequence"]))
            last_hash = current_hash
    return selected


def evaluate_selection(
    actual: dict[str, list[int]], ground_truth: dict[str, list[int]],
) -> dict[str, Any]:
    """Return deterministic exact-sequence precision/recall for F2 fixtures."""
    by_task = {}
    total_true_positive = total_actual = total_expected = 0
    for task, expected_items in ground_truth.items():
        expected = set(expected_items)
        selected = set(actual.get(task, []))
        true_positive = len(expected & selected)
        total_true_positive += true_positive
        total_actual += len(selected)
        total_expected += len(expected)
        by_task[task] = {
            "precision": round(true_positive / len(selected), 4) if selected else 0.0,
            "recall": round(true_positive / len(expected), 4) if expected else 1.0,
            "selected": sorted(selected),
            "expected": sorted(expected),
        }
    return {
        "precision": round(total_true_positive / total_actual, 4) if total_actual else 0.0,
        "recall": round(total_true_positive / total_expected, 4) if total_expected else 1.0,
        "by_task": by_task,
    }
