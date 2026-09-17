#!/usr/bin/env python3
"""Compare ClosedRoom's current dual-track ASR with one mixed-track ASR run.

The benchmark is read-only with respect to the recording. It bypasses the ASR
cache, never persists transcripts, forces the local provider, and emits only
aggregate metrics rather than meeting text.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from local_asr_server.audio_intelligence.audio_io import load_audio_samples
from local_asr_server.audio_strategy_benchmark import build_benchmark_report, build_run_report
from local_asr_server.asr_provider import ASR_PROVIDER_LOCAL
from local_asr_server.routers.helpers import _merge_track_transcriptions
from local_asr_server.services.transcription_service import TranscriptionService
from local_asr_server.settings import load_settings
from local_asr_server.transcription_quality import audio_stats, is_near_silent_track


SUPPORTED_AUDIO_SUFFIXES = {".wav", ".webm", ".ogg", ".m4a", ".mp4"}
TRACKS = {
    "mixed": {"id": "mixed", "source": "mixed", "label": "Conversazione"},
    "mic": {"id": "mic", "source": "mic", "label": "Tu"},
    "system": {"id": "system", "source": "system", "label": "Computer"},
}


def find_audio_file(session_dir: Path, stem: str) -> Path:
    matches = sorted(
        path
        for path in session_dir.glob(f"{stem}.*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES and not path.name.endswith(".part")
    )
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one finalized {stem} audio file in {session_dir}; found {len(matches)}"
        )
    return matches[0]


def inspect_input(path: Path) -> dict[str, Any]:
    stats = audio_stats(load_audio_samples(path))
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "duration_seconds": round(stats["duration_seconds"], 3),
        "rms": round(stats["rms"], 7),
        "peak": round(stats["peak"], 7),
        "near_silent": is_near_silent_track(stats),
    }


def transcribe_track(
    service: TranscriptionService,
    path: Path,
    track: dict[str, Any],
    *,
    model: str,
    language: str | None,
) -> tuple[dict[str, Any], float, float, bool]:
    started = time.perf_counter()
    skipped_result, stats = service._inspect_track(path, track)
    skipped = skipped_result is not None
    if skipped_result is not None:
        result = skipped_result
    else:
        result = service.transcribe_file(
            audio_path=str(path),
            model=model,
            language=language,
            task="transcribe",
            word_timestamps=False,
            condition_on_previous_text=False,
            asr_provider=ASR_PROVIDER_LOCAL,
            audio_duration_seconds=stats.get("duration_seconds"),
        )
    elapsed = time.perf_counter() - started
    processed_audio_seconds = 0.0 if skipped else float(stats.get("duration_seconds") or 0.0)
    return result, elapsed, processed_audio_seconds, skipped


def run_dual(
    service: TranscriptionService,
    paths: dict[str, Path],
    *,
    model: str,
    language: str | None,
) -> tuple[dict[str, Any], float, float, list[str]]:
    track_results = []
    wall_seconds = 0.0
    audio_seconds = 0.0
    skipped_tracks: list[str] = []
    for track_id in ("mic", "system"):
        track = {**TRACKS[track_id], "audio_file": paths[track_id].name}
        result, elapsed, processed, skipped = transcribe_track(
            service,
            paths[track_id],
            track,
            model=model,
            language=language,
        )
        wall_seconds += elapsed
        audio_seconds += processed
        if skipped:
            skipped_tracks.append(track_id)
        track_results.append({"track": track, "result": result})
    payload = _merge_track_transcriptions(
        track_results,
        model=model,
        language=language,
        elapsed=wall_seconds,
        recording_id="benchmark",
        asr_provider=ASR_PROVIDER_LOCAL,
    )
    return payload, wall_seconds, audio_seconds, skipped_tracks


def run_mixed(
    service: TranscriptionService,
    path: Path,
    *,
    model: str,
    language: str | None,
) -> tuple[dict[str, Any], float, float, list[str]]:
    track = {**TRACKS["mixed"], "audio_file": path.name}
    result, wall_seconds, audio_seconds, skipped = transcribe_track(
        service,
        path,
        track,
        model=model,
        language=language,
    )
    payload = _merge_track_transcriptions(
        [{"track": track, "result": result}],
        model=model,
        language=language,
        elapsed=wall_seconds,
        recording_id="benchmark",
        asr_provider=ASR_PROVIDER_LOCAL,
    )
    return payload, wall_seconds, audio_seconds, ["mixed"] if skipped else []


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(
        description="Compare current mic+system ASR with a single mixed-track ASR without mutating the recording."
    )
    parser.add_argument("session_dir", type=Path, help="Finalized recording session directory containing recording/mic/system audio files")
    parser.add_argument("--model", default=settings.get("default_model") or "")
    parser.add_argument("--language", default=settings.get("default_language") or "it")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--start-order", choices=("dual", "mixed"), default="dual")
    parser.add_argument("--output", type=Path, help="Optional JSON output path; stdout is used otherwise")
    args = parser.parse_args()

    session_dir = args.session_dir.expanduser().resolve()
    if not session_dir.is_dir():
        parser.error(f"Session directory does not exist: {session_dir}")
    if not args.model:
        parser.error("No ASR model configured; pass --model explicitly")
    if args.repeats < 1 or args.repeats > 9:
        parser.error("--repeats must be between 1 and 9")

    try:
        paths = {
            "mixed": find_audio_file(session_dir, "recording"),
            "mic": find_audio_file(session_dir, "mic"),
            "system": find_audio_file(session_dir, "system"),
        }
        input_tracks = {track_id: inspect_input(path) for track_id, path in paths.items()}
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    service = TranscriptionService()
    runs = []
    for repeat in range(args.repeats):
        dual_first = (args.start_order == "dual") == (repeat % 2 == 0)
        if dual_first:
            dual_payload, dual_wall, dual_audio, dual_skipped = run_dual(
                service, paths, model=args.model, language=args.language
            )
            mixed_payload, mixed_wall, mixed_audio, mixed_skipped = run_mixed(
                service, paths["mixed"], model=args.model, language=args.language
            )
            order = "dual_first"
        else:
            mixed_payload, mixed_wall, mixed_audio, mixed_skipped = run_mixed(
                service, paths["mixed"], model=args.model, language=args.language
            )
            dual_payload, dual_wall, dual_audio, dual_skipped = run_dual(
                service, paths, model=args.model, language=args.language
            )
            order = "mixed_first"

        run = build_run_report(
            dual_payload=dual_payload,
            mixed_payload=mixed_payload,
            dual_wall_seconds=dual_wall,
            mixed_wall_seconds=mixed_wall,
            dual_audio_seconds=dual_audio,
            mixed_audio_seconds=mixed_audio,
            order=order,
        )
        run["repeat"] = repeat + 1
        run["dual_track"]["skipped_tracks"] = dual_skipped
        run["mixed_track"]["skipped_tracks"] = mixed_skipped
        runs.append(run)

    report = build_benchmark_report(
        runs=runs,
        input_summary={"tracks": input_tracks},
        model=args.model,
        language=args.language,
    )
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
