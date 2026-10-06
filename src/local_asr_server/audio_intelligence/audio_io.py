from __future__ import annotations

import math
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from local_asr_server.paths import get_ffmpeg_path


TARGET_SAMPLE_RATE = 16_000
DEFAULT_WINDOW_SECONDS = 0.1


def load_audio_samples(path: Path, target_sr: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    """Load all audio samples from a file and return them as a mono float32 numpy array at 16kHz."""
    if _looks_like_wave(path):
        try:
            with wave.open(str(path), "rb") as wav:
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                if sample_rate == target_sr and channels == 1 and sample_width == 2:
                    frames = wav.readframes(wav.getnframes())
                    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception:
            pass

    ffmpeg = get_ffmpeg_path()
    process = subprocess.Popen(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(target_sr),
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, _ = process.communicate()
    if process.returncode != 0:
        raise OSError(f"ffmpeg failed with exit code {process.returncode}")

    return np.frombuffer(stdout, dtype=np.float32)


@dataclass(frozen=True)
class EnergyWindow:
    start: float
    end: float
    rms: float


def energy_windows_from_samples(
    samples: np.ndarray,
    *,
    sample_rate: int = TARGET_SAMPLE_RATE,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> list[EnergyWindow]:
    """Build RMS windows from an already-decoded mono sample buffer."""
    values = np.nan_to_num(
        np.asarray(samples, dtype=np.float32),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    frames_per_window = max(1, int(sample_rate * window_seconds))
    windows: list[EnergyWindow] = []
    for start_index in range(0, values.size, frames_per_window):
        chunk = values[start_index : start_index + frames_per_window]
        if chunk.size == 0:
            continue
        rms = float(np.sqrt(np.mean(np.square(chunk))))
        windows.append(
            EnergyWindow(
                start=start_index / sample_rate,
                end=(start_index + chunk.size) / sample_rate,
                rms=rms,
            )
        )
    return windows


def stream_audio_stats(
    path: Path,
    *,
    target_sr: int = TARGET_SAMPLE_RATE,
    chunk_samples: int = TARGET_SAMPLE_RATE * 4,
) -> dict[str, float]:
    """Inspect a track with bounded memory while preserving normalized stats."""
    sample_count = 0
    sum_squares = 0.0
    peak = 0.0
    for chunk in _iter_normalized_sample_chunks(
        path,
        target_sr=target_sr,
        chunk_samples=max(1, chunk_samples),
    ):
        values = np.nan_to_num(
            np.asarray(chunk, dtype=np.float32),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        if values.size == 0:
            continue
        sample_count += int(values.size)
        sum_squares += float(np.dot(values, values))
        peak = max(peak, float(np.max(np.abs(values))))
    if sample_count == 0:
        return {"rms": 0.0, "peak": 0.0, "duration_seconds": 0.0}
    return {
        "rms": math.sqrt(sum_squares / sample_count),
        "peak": peak,
        "duration_seconds": sample_count / target_sr,
    }


def can_reuse_normalized_samples_for_energy(
    path: Path,
    *,
    target_sr: int = TARGET_SAMPLE_RATE,
) -> bool:
    """Return whether normalized samples preserve the canonical WAV energy signal."""
    if not _looks_like_wave(path):
        return False
    try:
        with wave.open(str(path), "rb") as wav:
            return (
                wav.getframerate() == target_sr
                and wav.getnchannels() == 1
                and wav.getsampwidth() == 2
            )
    except (wave.Error, EOFError, OSError):
        return False


def iter_energy_windows(
    path: Path,
    *,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> Iterator[EnergyWindow]:
    if not _looks_like_wave(path):
        yield from _iter_ffmpeg_energy_windows(path, window_seconds=window_seconds)
        return
    try:
        yield from _iter_wave_energy_windows(path, window_seconds=window_seconds)
    except (wave.Error, EOFError, OSError):
        yield from _iter_ffmpeg_energy_windows(path, window_seconds=window_seconds)


def _iter_wave_energy_windows(path: Path, *, window_seconds: float) -> Iterator[EnergyWindow]:
    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        if sample_rate <= 0 or channels <= 0 or sample_width not in {1, 2, 3, 4}:
            raise wave.Error("unsupported wav format")

        frames_per_window = max(1, int(sample_rate * window_seconds))
        frame_index = 0
        while True:
            raw = wav.readframes(frames_per_window)
            if not raw:
                break
            frame_count = len(raw) // (sample_width * channels)
            if frame_count <= 0:
                break
            rms = _pcm_rms(raw, sample_width=sample_width, channels=channels)
            start = frame_index / sample_rate
            frame_index += frame_count
            end = frame_index / sample_rate
            yield EnergyWindow(start=start, end=end, rms=rms)


def _looks_like_wave(path: Path) -> bool:
    try:
        with path.open("rb") as audio_file:
            header = audio_file.read(12)
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    except OSError:
        return False


def _iter_ffmpeg_energy_windows(path: Path, *, window_seconds: float) -> Iterator[EnergyWindow]:
    ffmpeg = get_ffmpeg_path()
    frames_per_window = max(1, int(TARGET_SAMPLE_RATE * window_seconds))
    bytes_per_window = frames_per_window * 4
    process = subprocess.Popen(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(TARGET_SAMPLE_RATE),
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None:
        raise OSError("ffmpeg stdout unavailable")

    frame_index = 0
    try:
        while True:
            raw = process.stdout.read(bytes_per_window)
            if not raw:
                break
            sample_count = len(raw) // 4
            if sample_count <= 0:
                break
            values = struct.unpack("<" + "f" * sample_count, raw[: sample_count * 4])
            rms = math.sqrt(sum(sample * sample for sample in values) / sample_count)
            start = frame_index / TARGET_SAMPLE_RATE
            frame_index += sample_count
            end = frame_index / TARGET_SAMPLE_RATE
            yield EnergyWindow(start=start, end=end, rms=rms)
    finally:
        try:
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            process.wait(timeout=5)
        except Exception:
            process.kill()


def _pcm_rms(raw: bytes, *, sample_width: int, channels: int) -> float:
    samples = []
    step = sample_width * channels
    max_value = float((1 << ((sample_width * 8) - 1)) - 1)
    if max_value <= 0:
        return 0.0

    for offset in range(0, len(raw) - step + 1, step):
        channel_values = [
            _sample_to_int(raw[offset + channel * sample_width : offset + (channel + 1) * sample_width], sample_width)
            for channel in range(channels)
        ]
        samples.append(sum(channel_values) / channels)

    if not samples:
        return 0.0
    return min(1.0, math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / max_value)


def _sample_to_int(raw: bytes, sample_width: int) -> int:
    if sample_width == 1:
        return raw[0] - 128
    return int.from_bytes(raw, byteorder="little", signed=True)


def _iter_normalized_sample_chunks(
    path: Path,
    *,
    target_sr: int,
    chunk_samples: int,
) -> Iterator[np.ndarray]:
    if can_reuse_normalized_samples_for_energy(path, target_sr=target_sr):
        with wave.open(str(path), "rb") as wav:
            while True:
                raw = wav.readframes(chunk_samples)
                if not raw:
                    return
                yield np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    ffmpeg = get_ffmpeg_path()
    process = subprocess.Popen(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(target_sr),
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None:
        raise OSError("ffmpeg stdout unavailable")
    try:
        bytes_per_chunk = chunk_samples * 4
        while True:
            raw = process.stdout.read(bytes_per_chunk)
            if not raw:
                break
            usable = len(raw) - (len(raw) % 4)
            if usable:
                yield np.frombuffer(raw[:usable], dtype=np.float32)
        returncode = process.wait(timeout=5)
        if returncode != 0:
            raise OSError(f"ffmpeg failed with exit code {returncode}")
    finally:
        try:
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            if process.poll() is None:
                process.wait(timeout=5)
        except Exception:
            process.kill()
