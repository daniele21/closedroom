"""Run a local speaker-diarization A/B comparison on a finalized saved meeting.

Results are job-scoped and never update recording/transcription artifacts or settings.
Only bounded speaker/time intervals are persisted for UI preview. Meeting audio stays local.
"""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Callable

from local_asr_server.recordings import RecordingConflict, RecordingStore
from local_asr_server.audio_intelligence.audio_io import (
    canonical_wav_info, write_canonical_wav_slice,
)
from local_asr_server.paths import get_ffmpeg_path
from local_asr_server.speaker_diarization import (
    DIARIZATION_ENGINE, NEMOTRON3_ENGINE, LocalSpeakerDiarizationService,
)

BENCHMARK_JOB_TYPE = "diarization_benchmark"
ENGINE_OPTIONS = {
    "community-1": (DIARIZATION_ENGINE, "fast128"),
    "nemotron3-fast128": (NEMOTRON3_ENGINE, "fast128"),
    "nemotron3-compact": (NEMOTRON3_ENGINE, "c128-split-w8a8"),
}
SAMPLE_SECONDS = 300
MAX_PREVIEW_SEGMENTS = 300


def validate_options(engines: list[str], scope: str) -> None:
    if scope not in {"sample", "full"}:
        raise ValueError("Unsupported comparison scope")
    if not 2 <= len(engines) <= len(ENGINE_OPTIONS):
        raise ValueError("Select two or three diarization engines")
    if len(set(engines)) != len(engines) or any(engine not in ENGINE_OPTIONS for engine in engines):
        raise ValueError("Invalid or repeated diarization engine")


def _duration(path: Path) -> float:
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return float(info.duration)
    except (OSError, RuntimeError, ValueError):
        return 0.0


def _convert_to_wav(
    source: Path, destination: Path, *,
    seconds: int | None, cancel_requested: Callable[[], bool],
) -> float:
    """Decode a noncanonical local recording without loading the audio into RAM.

    Uses the application's own ffmpeg resolver; no remote processing. The run
    owns and deletes the output file. Cancellation kills and reaps ffmpeg.
    """
    command = [
        str(get_ffmpeg_path()), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
    ]
    if seconds is not None:
        command.extend(["-t", str(seconds)])
    command.extend(["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)])
    if cancel_requested():
        raise RuntimeError("Comparison cancelled")
    with subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    ) as child:
        while True:
            if cancel_requested():
                child.kill()
                child.communicate()
                raise RuntimeError("Comparison cancelled")
            try:
                _, _stderr = child.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                continue
        if child.returncode != 0:
            raise ValueError("Recording audio could not be decoded locally")
    info = canonical_wav_info(destination)
    if info is None or info.sample_count <= 0:
        raise ValueError("Recording audio contains no decodable samples")
    return info.duration_seconds


def _sample_wav(
    source: Path, destination: Path, *,
    cancel_requested: Callable[[], bool] = lambda: False,
) -> float:
    """Write at most five minutes of the selected track to a local temp WAV."""
    info = canonical_wav_info(source)
    if info is not None:
        if info.sample_count == 0:
            raise ValueError("Recording contains no audio samples")
        if cancel_requested():
            raise RuntimeError("Comparison cancelled")
        duration = min(info.duration_seconds, SAMPLE_SECONDS)
        write_canonical_wav_slice(
            source, destination, start_seconds=0.0, end_seconds=duration,
        )
        return duration
    return _convert_to_wav(
        source, destination, seconds=SAMPLE_SECONDS, cancel_requested=cancel_requested,
    )


def _preview_segments(segments: list[dict[str, Any]], limit_seconds: float) -> tuple[list[dict[str, Any]], bool]:
    preview = []
    for segment in sorted(segments, key=lambda item: (float(item["start"]), float(item["end"]))):
        start = max(0.0, float(segment["start"]))
        end = min(limit_seconds, float(segment["end"]))
        if end <= start or start >= limit_seconds:
            continue
        preview.append({
            "speaker": str(segment["speaker"])[:64],
            "start": round(start, 2),
            "end": round(end, 2),
        })
        if len(preview) > MAX_PREVIEW_SEGMENTS:
            return preview[:MAX_PREVIEW_SEGMENTS], True
    return preview, False


def run_benchmark(
    store: RecordingStore,
    recording_id: str,
    *,
    engines: list[str],
    scope: str,
    cancel_requested: Callable[[], bool],
    on_progress: Callable[[int, str, dict[str, Any]], None],
    service: LocalSpeakerDiarizationService | None = None,
) -> dict[str, Any]:
    validate_options(engines, scope)
    recording = store.get(recording_id, include_result=False)
    if recording.get("status") in {"recording", "finalizing", "recoverable", "interrupted"}:
        raise RecordingConflict("Finish the recording before comparing speakers")
    # Dual-track meetings diarize the remote-system track; the local mic is
    # already treated as one known speaker by the canonical transcription flow.
    tracks = store.transcribable_tracks(recording_id)
    track, path = next(
        ((track, path) for track, path in tracks if track.get("id") == "system"),
        next(((track, path) for track, path in tracks if track.get("id") == "mixed"), tracks[0]),
    )
    if path.stat().st_size == 0:
        raise RecordingConflict("Selected meeting track contains no audio")
    track_id = str(track["id"])
    service = service or LocalSpeakerDiarizationService()

    # Canonical PCM WAV can run directly in full mode. Other codecs, including
    # browser WebM, are decoded only into this job's temporary workspace.
    is_canonical = canonical_wav_info(path) is not None
    needs_temp = scope == "sample" or not is_canonical
    workspace = tempfile.TemporaryDirectory(prefix="closedroom-diarization-benchmark-") if needs_temp else nullcontext(None)
    with workspace as tmp:
        if cancel_requested():
            raise RuntimeError("Comparison cancelled")
        if scope == "sample":
            input_path = Path(tmp) / "sample.wav"
            duration = _sample_wav(path, input_path, cancel_requested=cancel_requested)
        elif not is_canonical:
            input_path = Path(tmp) / "normalized.wav"
            duration = _convert_to_wav(
                path, input_path, seconds=None, cancel_requested=cancel_requested,
            )
        else:
            duration = _duration(path)
            input_path = path
        if cancel_requested():
            raise RuntimeError("Comparison cancelled")

        runs = []
        for index, key in enumerate(engines):
            if cancel_requested():
                raise RuntimeError("Comparison cancelled")
            engine, preset = ENGINE_OPTIONS[key]
            on_progress(
                5 + int(index * 90 / len(engines)), "comparing",
                {"engine": key, "index": index + 1, "total": len(engines)},
            )
            started = time.perf_counter()
            item: dict[str, Any] = {"key": key, "engine": engine, "preset": preset if key != "community-1" else None}
            try:
                output = service.diarize_paths(
                    {"benchmark": input_path}, engine=engine, preset=preset,
                    cancel_requested=cancel_requested,
                )
                timeline = output["tracks"]["benchmark"]["segments"]
                elapsed = max(0.001, time.perf_counter() - started)
                preview_limit = min(SAMPLE_SECONDS, duration) if duration > 0 else SAMPLE_SECONDS
                preview, truncated = _preview_segments(timeline, preview_limit)
                item.update(
                    status="completed",
                    elapsed_seconds=round(elapsed, 2),
                    speed_vs_realtime=round(duration / elapsed, 2) if duration else None,
                    clusters=len({str(segment["speaker"]) for segment in timeline}),
                    preview=preview,
                    preview_truncated=truncated,
                )
            except Exception as exc:
                if cancel_requested():
                    raise RuntimeError("Comparison cancelled") from exc
                item.update(status="failed", error_type=type(exc).__name__)
            runs.append(item)
            on_progress(
                5 + int((index + 1) * 90 / len(engines)), "comparing",
                {"engine": key, "index": index + 1, "total": len(engines)},
            )
        if cancel_requested():
            raise RuntimeError("Comparison cancelled")
        completed = sum(item["status"] == "completed" for item in runs)
        return {
            "schema_version": 1,
            "outcome_status": "completed" if completed == len(runs) else "completed_with_warnings",
            "scope": scope,
            "track_id": track_id,
            "audio_seconds": round(duration, 2) if duration else None,
            "preview_seconds": round(min(SAMPLE_SECONDS, duration), 2) if duration else SAMPLE_SECONDS,
            "runs": runs,
            "reference_scored": False,
        }
