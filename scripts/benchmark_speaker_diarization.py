#!/usr/bin/env python3
"""Privacy-safe, same-audio A/B benchmark of local diarization engines.

Supports optional RTTM reference for an *approximate* 100 ms, no-collar DER.
Reports neither the input path nor any speaker identity/timeline/audio content.
Requires macOS with the native helper and locally accessible model weights.
The first run may download selected public weights (never meeting audio).
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import time
import wave

from local_asr_server.speaker_diarization import (
    DIARIZATION_ENGINE, NEMOTRON3_ENGINE, LocalSpeakerDiarizationService,
)

FRAME_SECONDS = 0.1


def _frame_sets(segments: list[dict], duration: float) -> list[set[str]]:
    frames: list[set[str]] = [set() for _ in range(math.ceil(duration / FRAME_SECONDS))]
    for item in segments:
        start = float(item["start"])
        end = float(item["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
            raise ValueError("Invalid diarization interval")
        low = max(0, math.ceil(start / FRAME_SECONDS - 0.5))
        high = min(len(frames), math.ceil(end / FRAME_SECONDS - 0.5))
        for idx in range(low, high):
            frames[idx].add(str(item["speaker"]))
    return frames


def approximate_der(reference: list[dict], hypothesis: list[dict], duration: float) -> float | None:
    """Approximate overlap-aware DER with optimal anonymous speaker permutation.

    No collar; 100 ms mid-point frame approximation. Not a pyannote/DIHARD score.
    """
    truth = _frame_sets(reference, duration)
    estimate = _frame_sets(hypothesis, duration)
    refs = sorted({speaker for frame in truth for speaker in frame})
    preds = sorted({speaker for frame in estimate for speaker in frame})
    if not refs:
        return None
    if len(refs) > 12 or len(preds) > 12:
        raise ValueError("Too many speakers to align in the lightweight benchmark")
    overlap = [[sum(p in hyp and r in gold for gold, hyp in zip(truth, estimate)) for r in refs] for p in preds]

    @lru_cache(None)
    def match(i: int, used: int) -> tuple[int, tuple[int, ...]]:
        if i == len(preds):
            return (0, ())
        best_score, tail = match(i + 1, used)
        best = (best_score, (-1,) + tail)
        for j in range(len(refs)):
            if used & (1 << j):
                continue
            score, tail = match(i + 1, used | (1 << j))
            candidate = (score + overlap[i][j], (j,) + tail)
            if candidate[0] > best[0]:
                best = candidate
        return best

    _, permutation = match(0, 0)
    mapping = {preds[i]: refs[j] for i, j in enumerate(permutation) if j >= 0}
    errors = reference_frames = 0
    for gold, predicted in zip(truth, estimate):
        ng, np = len(gold), len(predicted)
        reference_frames += ng
        correct = sum(mapping.get(p) in gold for p in predicted)
        errors += max(ng - np, 0) + max(np - ng, 0) + min(ng, np) - correct
    return round(errors / reference_frames, 5) if reference_frames else None


def parse_rttm(path: Path) -> list[dict]:
    timeline = []
    recording_names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        fields = raw.split()
        if len(fields) < 8 or fields[0] != "SPEAKER":
            raise ValueError("RTTM must contain SPEAKER records only")
        recording_names.add(fields[1])
        start = float(fields[3])
        duration = float(fields[4])
        timeline.append({"speaker": fields[7], "start": start, "end": start + duration})
    if len(recording_names) != 1:
        raise ValueError("RTTM must describe exactly one recording")
    return timeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True, help="Finalized PCM WAV file, never uploaded")
    parser.add_argument("--reference-rttm", type=Path, help="Optional human-annotated speaker RTTM")
    parser.add_argument("--output", type=Path, help="Write aggregate metrics only")
    args = parser.parse_args()

    with wave.open(str(args.audio), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    reference = parse_rttm(args.reference_rttm) if args.reference_rttm else None
    service = LocalSpeakerDiarizationService()
    results = []
    for engine, preset in (
        (DIARIZATION_ENGINE, "fast128"),
        (NEMOTRON3_ENGINE, "fast128"),
        (NEMOTRON3_ENGINE, "c128-split-w8a8"),
    ):
        start = time.perf_counter()
        item = {"engine": engine, "preset": preset if engine == NEMOTRON3_ENGINE else None}
        try:
            result = service.diarize_paths({"benchmark": args.audio}, engine=engine, preset=preset)
            segments = result["tracks"]["benchmark"]["segments"]
            elapsed = time.perf_counter() - start
            item.update(
                status="completed", elapsed_seconds=round(elapsed, 3),
                audio_seconds=round(duration, 3),
                speed_vs_realtime=round(duration / elapsed, 2) if elapsed else None,
                clusters=len({str(s["speaker"]) for s in segments}),
            )
            if reference is not None:
                item["approx_der_100ms_no_collar"] = approximate_der(reference, segments, duration)
        except Exception as exc:
            item.update(status="failed", error_type=type(exc).__name__)
        results.append(item)
    report = {"schema_version": 1, "reference_scored": reference is not None, "runs": results}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
