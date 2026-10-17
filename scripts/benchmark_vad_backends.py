#!/usr/bin/env python3
"""Benchmark Silero VAD against ClosedRoom's RMS fallback without retaining meeting content."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from local_asr_server.audio_intelligence.audio_io import (
    canonical_wav_info,
    iter_energy_windows,
    iter_normalized_audio_chunks,
    load_audio_samples,
)
from local_asr_server.audio_intelligence.features import _speech_threshold, _speech_windows
from local_asr_server.audio_intelligence.vad import (
    detect_speech_windows_vad,
    detect_speech_windows_vad_chunks,
)
from local_asr_server.audio_intelligence.vad_benchmark import (
    build_benchmark_report,
    build_case_report,
    discover_finalized_recording_tracks,
    reference_segment_windows,
)
from local_asr_server.settings import load_settings


def _silero(path: Path) -> tuple[list[dict[str, float]], float]:
    canonical = canonical_wav_info(path)
    started = time.perf_counter()
    if canonical is not None:
        windows = detect_speech_windows_vad_chunks(
            iter_normalized_audio_chunks(path, chunk_samples=512),
            total_samples=canonical.sample_count,
            sr=canonical.sample_rate,
        )
    else:
        samples = load_audio_samples(path)
        windows = detect_speech_windows_vad(samples, sr=16_000)
    return windows, time.perf_counter() - started


def _rms(path: Path) -> tuple[list[dict[str, float]], float, float]:
    started = time.perf_counter()
    energy = list(iter_energy_windows(path))
    threshold = _speech_threshold(energy)
    raw = _speech_windows(energy, threshold=threshold, channel="audio")
    windows = [
        {"start": float(item["source_start"]), "end": float(item["source_end"])}
        for item in raw
    ]
    duration = energy[-1].end if energy else 0.0
    return windows, time.perf_counter() - started, duration


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Silero VAD and RMS fallback using privacy-safe aggregate evidence."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio", action="append", help="Local audio path; repeat for multiple tracks.")
    source.add_argument(
        "--latest-recordings",
        type=int,
        metavar="N",
        help="Benchmark tracks from the N newest finalized ClosedRoom recordings.",
    )
    parser.add_argument(
        "--recordings-root",
        type=Path,
        help="Override the configured ClosedRoom recordings directory for --latest-recordings.",
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if args.latest_recordings is not None and args.latest_recordings < 1:
        parser.error("--latest-recordings must be >= 1")

    if args.latest_recordings is not None:
        configured_root = args.recordings_root
        if configured_root is None:
            configured_root = Path(str(load_settings()["recordings_dir"]))
        audio_paths = discover_finalized_recording_tracks(
            configured_root,
            recording_limit=args.latest_recordings,
        )
        if not audio_paths:
            parser.error("No finalized ClosedRoom recording tracks found")
    else:
        audio_paths = [Path(raw_path).expanduser().resolve() for raw_path in (args.audio or [])]

    cases = []
    for index, path in enumerate(audio_paths):
        if not path.is_file():
            raise FileNotFoundError(path)

        silero_runs = []
        rms_runs = []
        representative_silero: list[dict[str, float]] = []
        representative_rms: list[dict[str, float]] = []
        duration_seconds = 0.0

        # Alternate order across repeats to reduce systematic warm-cache bias.
        for repeat_index in range(args.repeat):
            if repeat_index % 2 == 0:
                silero_windows, silero_wall = _silero(path)
                rms_windows, rms_wall, duration = _rms(path)
            else:
                rms_windows, rms_wall, duration = _rms(path)
                silero_windows, silero_wall = _silero(path)
            representative_silero = silero_windows
            representative_rms = rms_windows
            duration_seconds = max(duration_seconds, duration)
            silero_runs.append({
                "wall_seconds": silero_wall,
                "speech_seconds": sum(max(0.0, item["end"] - item["start"]) for item in silero_windows),
                "window_count": len(silero_windows),
            })
            rms_runs.append({
                "wall_seconds": rms_wall,
                "speech_seconds": sum(max(0.0, item["end"] - item["start"]) for item in rms_windows),
                "window_count": len(rms_windows),
            })

        canonical = canonical_wav_info(path)
        if canonical is not None:
            duration_seconds = canonical.duration_seconds
        cases.append(build_case_report(
            index=index,
            bytes_total=path.stat().st_size,
            duration_seconds=duration_seconds,
            canonical_wav=canonical is not None,
            silero_runs=silero_runs,
            rms_runs=rms_runs,
            silero_windows=representative_silero,
            rms_windows=representative_rms,
            reference_windows=reference_segment_windows(path),
        ))

    report = build_benchmark_report(cases)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
