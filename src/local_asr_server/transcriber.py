"""
transcriber.py — Transcription engine wrapper and orchestrator for local-asr-server.

Encapsulates the MLX Whisper runtime execution, stdout capturing, result caching,
and model caching logic.
"""

from __future__ import annotations

import os
import sys
import time
import math
import json
import queue
import hashlib
import logging
import asyncio
import threading
import contextlib
import tempfile
from pathlib import Path
from typing import Optional, Any, Callable, Dict, Generator

from local_asr_server.paths import get_cache_dir
from local_asr_server.transcription_quality import clean_segments, filter_segments_by_vad
from local_asr_server.asr_models import (
    NEMOTRON_BACKEND,
    get_asr_backend,
    is_nemotron_model,
    resolve_nemotron_language,
)
from local_asr_server.asr_provider import (
    VAD_GUIDED_DEFAULT,
    VAD_POST_FILTER_DEFAULT,
    public_asr_metadata,
)

logger = logging.getLogger("uvicorn.error")
CACHE_DIR = get_cache_dir()
TRANSCRIPTION_CACHE_VERSION = "asr-v2"
TRANSCRIPTION_CACHE_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_TEMPERATURE = 0.0
DEFAULT_COMPRESSION_RATIO_THRESHOLD = 2.2
DEFAULT_LOGPROB_THRESHOLD = -0.7
DEFAULT_NO_SPEECH_THRESHOLD = 0.35


# ── Utility Helpers ───────────────────────────────────────────────────────────

def str_to_bool(value: str | bool | None, default: bool = False) -> bool:
    """Convert a string or boolean configuration value to a real boolean."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.lower() in {"1", "true", "yes", "y", "on"}


def resolve_model(model_name: str) -> str:
    """
    Resolve a model name to a local absolute path if it exists in LM Studio
    or is already an absolute/relative path.
    """
    if not model_name:
        return model_name
    if model_name.startswith("/") or model_name.startswith("."):
        return model_name
    # Check LM Studio path
    lm_studio_path = Path(f"~/.lmstudio/models/{model_name}").expanduser()
    if lm_studio_path.exists():
        return str(lm_studio_path)
    return model_name


try:
    from tqdm import tqdm
    class DownloadProgressTqdm(tqdm):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._report()

        def update(self, n=1):
            super().update(n)
            self._report()

        def _report(self):
            if self.total and self.total > 0:
                percent = (self.n / self.total) * 100
                print(f"DOWNLOAD_PROGRESS:{percent:.1f}:{self.n}:{self.total}")
                sys.stdout.flush()
except ImportError:
    class DownloadProgressTqdm:
        def __init__(self, *args, **kwargs):
            self.total = kwargs.get("total", 0)
            self.n = 0
            self._report()
        def update(self, n=1):
            self.n += n
            self._report()
        def close(self):
            pass
        def _report(self):
            if self.total and self.total > 0:
                percent = (self.n / self.total) * 100
                print(f"DOWNLOAD_PROGRESS:{percent:.1f}:{self.n}:{self.total}")
                sys.stdout.flush()


def is_model_cached(model_name: str) -> bool:
    """
    Check if the specified Hugging Face model resides in the local cache,
    or is a direct local file path.
    """
    resolved = resolve_model(model_name)
    if resolved.startswith("/") or resolved.startswith("."):
        return Path(resolved).exists()
    
    # Hugging Face cache structure check
    folder_name = "models--" + resolved.replace("/", "--")
    cache_dir = Path(os.path.expanduser("~/.cache/huggingface/hub")) / folder_name
    if cache_dir.exists():
        snapshots_dir = cache_dir / "snapshots"
        if snapshots_dir.exists():
            for p in snapshots_dir.iterdir():
                if p.is_dir():
                    # Look for model weight files (like weights.npz, model.safetensors, or model.bin)
                    # and check that their resolved symlink target exists and is not incomplete.
                    for f in p.iterdir():
                        if f.name == "weights.npz" or f.suffix in (".npz", ".safetensors", ".bin"):
                            try:
                                resolved_sym = f.resolve()
                                if resolved_sym.exists() and not resolved_sym.name.endswith(".incomplete"):
                                    return True
                            except Exception:
                                pass
    return False


class ThreadStdoutCapture:
    """Capture stdout line-by-line inside a worker thread and feed it into a Queue."""
    def __init__(self, q: queue.Queue):
        self.q = q
        self.original_stdout = sys.stdout

    def write(self, text: str):
        self.original_stdout.write(text)
        self.original_stdout.flush()
        if text.strip():
            self.q.put(text.strip())

    def flush(self):
        self.original_stdout.flush()


# ── Caching Layer ─────────────────────────────────────────────────────────────

def _clean_nan_values(val: Any) -> Any:
    """Recursively clean float('nan') or float('inf') values into None to ensure valid JSON."""
    if isinstance(val, dict):
        return {k: _clean_nan_values(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_clean_nan_values(x) for x in val]
    elif isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    return val


def generate_cache_key(
    audio_hash: str,
    model: str,
    language: Optional[str],
    task: str,
    word_timestamps: str | bool,
    initial_prompt: Optional[str],
    temperature: Optional[float],
    condition_on_previous_text: str | bool,
    vad_guided: str | bool = VAD_GUIDED_DEFAULT,
    vad_post_filter: str | bool = VAD_POST_FILTER_DEFAULT,
    asr_provider: str = "local",
    backend: str | None = None,
    provider_options: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a unique SHA-256 cache key based on the audio hash and run parameters."""
    params = {
        "version": TRANSCRIPTION_CACHE_VERSION,
        "audio_hash": audio_hash,
        "model": model,
        "language": language or None,
        "task": task,
        "word_timestamps": str_to_bool(word_timestamps),
        "initial_prompt": initial_prompt or None,
        "temperature": temperature,
        "condition_on_previous_text": str_to_bool(condition_on_previous_text),
        "vad_guided": str_to_bool(vad_guided, VAD_GUIDED_DEFAULT),
        "vad_post_filter": str_to_bool(vad_post_filter, VAD_POST_FILTER_DEFAULT),
        "asr_provider": asr_provider or "local",
        "backend": backend or "",
        "provider_options": provider_options or {},
    }
    return hashlib.sha256(
        json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def hash_audio_file(path: str | Path) -> str:
    """Hash audio bytes without loading a full recording into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_transcription_cache_file(path: Path) -> bool:
    stem = path.stem.lower()
    return (
        path.suffix == ".json"
        and len(stem) == 64
        and all(character in "0123456789abcdef" for character in stem)
    )


def prune_transcription_cache(
    *,
    max_bytes: int | None = None,
    protected_cache_key: str | None = None,
) -> dict[str, int]:
    """Bound only ephemeral SHA-keyed ASR JSON cache files using LRU mtime."""
    if max_bytes is None:
        max_bytes = TRANSCRIPTION_CACHE_MAX_BYTES
    max_bytes = max(0, int(max_bytes))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    protected = CACHE_DIR / f"{protected_cache_key}.json" if protected_cache_key else None
    entries: list[tuple[Path, int, int]] = []
    for path in CACHE_DIR.glob("*.json"):
        if not _is_transcription_cache_file(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path, stat.st_size, stat.st_mtime_ns))

    total_bytes = sum(size for _, size, _ in entries)
    removed_files = 0
    removed_bytes = 0

    if protected is not None and protected.exists():
        try:
            protected_size = protected.stat().st_size
        except OSError:
            protected_size = 0
        if protected_size > max_bytes:
            try:
                protected.unlink()
                total_bytes -= protected_size
                removed_files += 1
                removed_bytes += protected_size
            except OSError:
                pass
            protected = None

    for path, size, _mtime_ns in sorted(entries, key=lambda item: item[2]):
        if total_bytes <= max_bytes:
            break
        if protected is not None and path == protected:
            continue
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError:
            continue
        total_bytes -= size
        removed_files += 1
        removed_bytes += size

    return {
        "remaining_bytes": max(0, total_bytes),
        "removed_bytes": removed_bytes,
        "removed_files": removed_files,
    }


def get_cached_result(cache_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve an ASR cache hit and promote it in the bounded LRU."""
    cache_file = CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            try:
                os.utime(cache_file, None)
            except OSError:
                pass
            return _clean_nan_values(data)
        except Exception as e:
            logger.warning(f"Failed to read cache file {cache_file}: {e}")
    return None


def save_cached_result(cache_key: str, data: Dict[str, Any]) -> None:
    """Atomically save one ASR result, then bound only the ephemeral cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{cache_key}.json"
    temp_path: Path | None = None
    try:
        cleaned_data = _clean_nan_values(data)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=CACHE_DIR,
            prefix=f".{cache_key}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(cleaned_data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, cache_file)
        temp_path = None
        prune_transcription_cache(protected_cache_key=cache_key)
        logger.info(f"Saved transcription to cache: {cache_file}")
    except Exception as e:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        logger.warning(f"Failed to write cache file {cache_file}: {e}")


# ── Whisper API Invocation ────────────────────────────────────────────────────

def _transcribe(
    *,
    audio_path: str,
    model: str,
    language: Optional[str],
    task: str,
    word_timestamps: bool,
    initial_prompt: Optional[str],
    temperature: Optional[float],
    condition_on_previous_text: bool,
    verbose: Optional[bool],
    compression_ratio_threshold: float | None = DEFAULT_COMPRESSION_RATIO_THRESHOLD,
    logprob_threshold: float | None = DEFAULT_LOGPROB_THRESHOLD,
    no_speech_threshold: float | None = DEFAULT_NO_SPEECH_THRESHOLD,
    hallucination_silence_threshold: float | None = None,
    audio_duration_seconds: float | None = None,
) -> dict:
    """Run the selected ASR runtime while preserving the shared result shape."""
    if is_nemotron_model(model):
        if task != "transcribe":
            raise ValueError("Nemotron ASR supports transcription only; select 'transcribe'.")
        from mlx_audio.stt import load

        nemotron_language = resolve_nemotron_language(language)
        # Nemotron's offline generate() builds a full attention matrix for the
        # input. That grows quadratically with a recording's duration and can
        # exhaust MLX's single-buffer limit. Its native streaming iterator
        # keeps encoder state bounded while returning a cumulative result.
        generated = None
        for generated in load(resolve_model(model)).stream_generate(
            audio_path,
            language=nemotron_language,
        ):
            sentences = getattr(generated, "sentences", []) or []
            if sentences:
                processed = max(float(sentence.end) for sentence in sentences)
                print(f"ASR_PROGRESS:{processed:.3f}")
        if generated is None:
            return {
                "text": "",
                "segments": [],
                "language": nemotron_language or "",
                "metadata": {"backend": NEMOTRON_BACKEND, "timestamps_available": True},
            }
        text = (getattr(generated, "text", "") or "").strip()
        segments = [
            {
                "id": index,
                "start": float(sentence.start),
                "end": float(sentence.end),
                "text": (sentence.text or "").strip(),
            }
            for index, sentence in enumerate(getattr(generated, "sentences", []) or [])
            if (sentence.text or "").strip()
        ]
        return {
            "text": text,
            "segments": segments,
            "language": nemotron_language or "",
            "metadata": {"backend": NEMOTRON_BACKEND, "timestamps_available": True},
        }

    import mlx_whisper

    if not language:
        language = None

    resolved_model = resolve_model(model)

    kwargs = {
        "path_or_hf_repo": resolved_model,
        "language": language,
        "task": task,
        "word_timestamps": word_timestamps,
        "initial_prompt": initial_prompt,
        "temperature": DEFAULT_TEMPERATURE if temperature is None else temperature,
        "condition_on_previous_text": condition_on_previous_text,
        "verbose": verbose,
        "compression_ratio_threshold": compression_ratio_threshold,
        "logprob_threshold": logprob_threshold,
        "no_speech_threshold": no_speech_threshold,
    }
    if hallucination_silence_threshold is not None:
        kwargs["hallucination_silence_threshold"] = hallucination_silence_threshold

    # Filter out None values to let mlx_whisper use its defaults
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    return mlx_whisper.transcribe(
        audio_path,
        **kwargs,
    )


def _postprocess_full_track_result(audio_path: str, result: dict, *, vad_post_filter: bool) -> dict:
    """Preserve raw ASR output while producing a cleaned result for users.

    VAD is advisory only: an unavailable detector or no detected speech never
    converts a valid Whisper result into an empty transcript.
    """
    raw_segments = [dict(segment) for segment in result.get("segments", []) or []]
    if result.get("metadata", {}).get("timestamps_available") is False:
        cleaned = dict(result)
        cleaned["raw_text"] = result.get("text", "")
        cleaned["raw_segments"] = raw_segments
        cleaned["metadata"] = {
            **dict(result.get("metadata") or {}),
            "quality_filter_enabled": False,
            "quality_filter_skipped_reason": "timestamps_unavailable",
            "raw_segments_count": len(raw_segments),
        }
        return cleaned
    segments, dropped = clean_segments(raw_segments)
    metadata = dict(result.get("metadata") or {})
    metadata.update({"quality_filter_enabled": True, "raw_segments_count": len(raw_segments)})
    if vad_post_filter:
        try:
            from local_asr_server.audio_intelligence.audio_io import load_audio_samples
            from local_asr_server.audio_intelligence.vad import detect_speech_windows_vad
            vad_windows = detect_speech_windows_vad(load_audio_samples(Path(audio_path)), sr=16000)
            if vad_windows:
                segments, vad_dropped = filter_segments_by_vad(segments, vad_windows)
                dropped.extend(vad_dropped)
                metadata.update({"vad_filter_enabled": True, "vad_windows_count": len(vad_windows)})
            else:
                metadata.update({"vad_filter_enabled": False, "vad_filter_fallback": "no_speech_windows_detected"})
        except Exception as exc:
            logger.warning("[ASR Quality] VAD post-filter unavailable; retaining cleaned Whisper output: %s", exc)
            metadata.update({"vad_filter_enabled": False, "vad_filter_fallback": "vad_detection_failed"})
    cleaned = dict(result)
    cleaned["raw_text"] = result.get("text", "")
    cleaned["raw_segments"] = raw_segments
    cleaned["segments"] = segments
    cleaned["text"] = " ".join((segment.get("text") or "").strip() for segment in segments).strip()
    metadata.update({"dropped_segments_count": len(dropped), "dropped_segments": dropped[:200]})
    cleaned["metadata"] = metadata
    return cleaned


def _transcribe_vad_guided(
    *,
    audio_path: str,
    model: str,
    language: Optional[str],
    task: str,
    word_timestamps: bool,
    initial_prompt: Optional[str],
    temperature: Optional[float],
    condition_on_previous_text: bool,
    verbose: Optional[bool],
) -> dict:
    """Run transcription guided by Silero VAD / RMS fallback to skip silent parts."""
    import numpy as np
    import tempfile
    import wave
    from local_asr_server.audio_intelligence.audio_io import (
        canonical_wav_info,
        iter_energy_windows,
        iter_normalized_audio_chunks,
        load_audio_samples,
        write_canonical_wav_slice,
    )
    from local_asr_server.audio_intelligence.vad import (
        detect_speech_windows_vad,
        detect_speech_windows_vad_chunks,
    )
    from local_asr_server.audio_intelligence.features import _speech_threshold, _speech_windows

    def full_track_fallback(reason: str, *, vad_windows_count: int | None = None) -> dict:
        """Keep VAD an optimization: it must never suppress a transcription."""
        result = _transcribe(
            audio_path=audio_path,
            model=model,
            language=language,
            task=task,
            word_timestamps=word_timestamps,
            initial_prompt=initial_prompt,
            temperature=temperature,
            condition_on_previous_text=condition_on_previous_text,
            verbose=verbose,
        )
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            result["metadata"] = metadata
        metadata.update(
            {
                "vad_guided": True,
                "vad_fallback": True,
                "vad_fallback_reason": reason,
                "vad_windows_count": vad_windows_count,
            }
        )
        return result

    source_path = Path(audio_path)
    canonical = canonical_wav_info(source_path)
    samples = None
    logger.info(f"[VAD Guided ASR] Loading audio from: {audio_path}")
    if canonical is not None:
        duration = canonical.duration_seconds
        logger.info(f"[VAD Guided ASR] Running streaming VAD detection. Duration: {duration:.2f}s")
        try:
            raw_windows = detect_speech_windows_vad_chunks(
                iter_normalized_audio_chunks(source_path, chunk_samples=512),
                total_samples=canonical.sample_count,
                sr=canonical.sample_rate,
            )
        except Exception as e:
            logger.warning(f"[VAD Guided ASR] Streaming Silero VAD failed, falling back to RMS energy windows: {e}")
            try:
                windows = list(iter_energy_windows(source_path))
                threshold = _speech_threshold(windows)
                raw_w = _speech_windows(windows, threshold=threshold, channel="audio")
                raw_windows = [{"start": w["source_start"], "end": w["source_end"]} for w in raw_w]
            except Exception as e2:
                logger.warning(f"[VAD Guided ASR] Fallback RMS failed, transcribing full-track: {e2}")
                return full_track_fallback("vad_and_rms_detection_failed")
    else:
        try:
            samples = load_audio_samples(source_path)
        except Exception as e:
            logger.warning(f"[VAD Guided ASR] Failed to load samples, falling back to full-track: {e}")
            return full_track_fallback("audio_load_failed")

        duration = len(samples) / 16000.0
        logger.info(f"[VAD Guided ASR] Running VAD detection. Duration: {duration:.2f}s")
        try:
            raw_windows = detect_speech_windows_vad(samples, sr=16000)
        except Exception as e:
            logger.warning(f"[VAD Guided ASR] Silero VAD failed, falling back to RMS energy windows: {e}")
            try:
                windows = list(iter_energy_windows(source_path))
                threshold = _speech_threshold(windows)
                raw_w = _speech_windows(windows, threshold=threshold, channel="audio")
                raw_windows = [{"start": w["source_start"], "end": w["source_end"]} for w in raw_w]
            except Exception as e2:
                logger.warning(f"[VAD Guided ASR] Fallback RMS failed, transcribing full-track: {e2}")
                return full_track_fallback("vad_and_rms_detection_failed")

    if not raw_windows:
        logger.warning(
            "[VAD Guided ASR] No speech windows detected; falling back to full-track transcription."
        )
        return full_track_fallback("no_speech_windows_detected", vad_windows_count=0)

    logger.info(f"[VAD Guided ASR] Detected {len(raw_windows)} speech segments to transcribe.")
    combined_segments = []
    combined_text_parts = []
    segment_id = 0
    PADDING = 0.5

    for idx, window in enumerate(raw_windows):
        start = max(0.0, window["start"] - PADDING)
        end = min(duration, window["end"] + PADDING)
        if end - start < 0.1:
            continue

        # Use context manager or NamedTemporaryFile cleanly.
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        try:
            if canonical is not None:
                write_canonical_wav_slice(
                    source_path,
                    Path(tmp_path),
                    start_seconds=start,
                    end_seconds=end,
                )
            else:
                assert samples is not None
                start_sample = int(start * 16000)
                end_sample = int(end * 16000)
                slice_samples = samples[start_sample:end_sample]
                int_samples = (slice_samples * 32768.0).clip(-32768, 32767).astype(np.int16)
                with wave.open(tmp_path, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(int_samples.tobytes())

            logger.info(f"[VAD Guided ASR] Segment {idx+1}/{len(raw_windows)}: transcribing {start:.2f}s --> {end:.2f}s")
            res = _transcribe(
                audio_path=tmp_path,
                model=model,
                language=language,
                task=task,
                word_timestamps=word_timestamps,
                initial_prompt=initial_prompt,
                temperature=temperature,
                condition_on_previous_text=condition_on_previous_text,
                verbose=verbose,
            )

            # Shift segment timestamps
            for seg in res.get("segments", []):
                seg["id"] = segment_id
                segment_id += 1
                seg["start"] = round(seg["start"] + start, 3)
                seg["end"] = round(seg["end"] + start, 3)
                if "words" in seg:
                    for w in seg["words"]:
                        w["start"] = round(w["start"] + start, 3)
                        w["end"] = round(w["end"] + start, 3)
                combined_segments.append(seg)
                
            text = res.get("text", "").strip()
            if text:
                combined_text_parts.append(text)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    combined_text = " ".join(combined_text_parts)
    if not combined_text.strip() and not combined_segments:
        logger.warning(
            "[VAD Guided ASR] VAD windows produced an empty transcript; "
            "falling back to full-track transcription."
        )
        return full_track_fallback(
            "vad_windows_produced_empty_transcript",
            vad_windows_count=len(raw_windows),
        )

    return {"text": combined_text, "segments": combined_segments}


# ── Transcription Orchestration ───────────────────────────────────────────────

def transcribe_file_sync(
    audio_path: str,
    model: str,
    language: Optional[str],
    task: str,
    word_timestamps: bool,
    initial_prompt: Optional[str],
    temperature: Optional[float],
    condition_on_previous_text: bool,
    verbose: Optional[bool] = None,
    vad_guided: bool = VAD_GUIDED_DEFAULT,
    vad_post_filter: bool = VAD_POST_FILTER_DEFAULT,
    audio_duration_seconds: float | None = None,
) -> dict:
    """Run transcription synchronously for the given file."""
    if vad_guided:
        result = _transcribe_vad_guided(
            audio_path=audio_path,
            model=model,
            language=language,
            task=task,
            word_timestamps=word_timestamps,
            initial_prompt=initial_prompt,
            temperature=temperature,
            condition_on_previous_text=condition_on_previous_text,
            verbose=verbose,
        )
        return _postprocess_full_track_result(audio_path, result, vad_post_filter=False)
    result = _transcribe(
        audio_path=audio_path,
        model=model,
        language=language,
        task=task,
        word_timestamps=word_timestamps,
        initial_prompt=initial_prompt,
        temperature=temperature,
        condition_on_previous_text=condition_on_previous_text,
        verbose=verbose,
        audio_duration_seconds=audio_duration_seconds,
    )
    return _postprocess_full_track_result(audio_path, result, vad_post_filter=vad_post_filter)


async def transcribe_stream_generator(
    audio_path: str,
    model: str,
    language: Optional[str],
    task: str,
    word_timestamps: str | bool,
    initial_prompt: Optional[str],
    temperature: Optional[float],
    condition_on_previous_text: str | bool,
    cache_key: str,
    audio_filename: Optional[str],
    recording_id: Optional[str],
    transcription_store: Any,
    started_at: float,
    vad_guided: str | bool = VAD_GUIDED_DEFAULT,
    vad_post_filter: str | bool = VAD_POST_FILTER_DEFAULT,
    asr_provider: str = "local",
    backend: str | None = None,
    provider_options: Optional[Dict[str, Any]] = None,
    payload_postprocessor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
) -> Generator[str, None, None]:
    """
    Stream transcription updates using NDJSON. Starts a background worker thread
    to run mlx-whisper, and yields progress/transcription outputs over an queue.
    """
    q: queue.Queue = queue.Queue()
    
    # Send initial progress payload
    backend = get_asr_backend(model)
    backend_label = "Nemotron" if backend == NEMOTRON_BACKEND else "Whisper"
    model_is_cached = is_model_cached(model)
    logger.info(f"[Transcriber] Model cache status for {model}: cached={model_is_cached}")

    if model_is_cached:
        yield json.dumps({
            "type": "progress",
            "step": "loading_model",
            "message": f"Caricamento del modello {backend_label} in memoria..."
        }) + "\n"
    else:
        yield json.dumps({
            "type": "progress",
            "step": "downloading",
            "message": f"Download del modello '{model}' da Hugging Face (~1.6 GB)..."
        }) + "\n"

    transcribe_result = {}
    transcribe_error = None

    def worker():
        nonlocal transcribe_error
        try:
            logger.info(f"[Transcriber] [Worker Thread] Starting transcription for {audio_path}")
            capture = ThreadStdoutCapture(q)
            with contextlib.redirect_stdout(capture):
                resolved_model = resolve_model(model)
                if not resolved_model.startswith("/") and not resolved_model.startswith("."):
                    if not is_model_cached(resolved_model):
                        from huggingface_hub import snapshot_download
                        print(f"DOWNLOAD_START:{model}")
                        sys.stdout.flush()
                        try:
                            snapshot_download(
                                repo_id=resolved_model,
                                tqdm_class=DownloadProgressTqdm,
                            )
                        except Exception as e:
                            logger.warning(f"Pre-download failed (will retry in mlx_whisper): {e}")
                        print(f"DOWNLOAD_COMPLETE:{model}")
                        sys.stdout.flush()

                if str_to_bool(vad_guided, VAD_GUIDED_DEFAULT):
                    res = _postprocess_full_track_result(audio_path, _transcribe_vad_guided(
                        audio_path=audio_path,
                        model=model,
                        language=language,
                        task=task,
                        word_timestamps=str_to_bool(word_timestamps),
                        initial_prompt=initial_prompt,
                        temperature=temperature,
                        condition_on_previous_text=str_to_bool(condition_on_previous_text, False),
                        verbose=True,
                    ), vad_post_filter=False)
                else:
                    res = _postprocess_full_track_result(audio_path, _transcribe(
                        audio_path=audio_path,
                        model=model,
                        language=language,
                        task=task,
                        word_timestamps=str_to_bool(word_timestamps),
                        initial_prompt=initial_prompt,
                        temperature=temperature,
                        condition_on_previous_text=str_to_bool(condition_on_previous_text, False),
                        verbose=True,
                    ), vad_post_filter=str_to_bool(vad_post_filter, VAD_POST_FILTER_DEFAULT))
                transcribe_result.update(res)
            logger.info(f"[Transcriber] [Worker Thread] Transcription completed successfully")
        except Exception as e:
            logger.error(f"[Transcriber] [Worker Thread] Transcription failed: {e}", exc_info=True)
            transcribe_error = e

    t = threading.Thread(target=worker)
    t.start()

    # Poll thread stdout capture queue
    while t.is_alive() or not q.empty():
        try:
            msg = q.get_nowait()
            logger.info(f"[Transcriber] [Live Segment] {msg}")

            if msg.startswith("DOWNLOAD_PROGRESS:"):
                parts = msg.split(":")
                if len(parts) >= 4:
                    percent_str = parts[1]
                    downloaded_bytes = int(parts[2])
                    total_bytes = int(parts[3])
                    downloaded_mb = downloaded_bytes / (1024 * 1024)
                    total_mb = total_bytes / (1024 * 1024)
                    yield json.dumps({
                        "type": "progress",
                        "step": "downloading",
                        "percent": float(percent_str),
                        "message": f"Download del modello '{model}': {percent_str}% ({downloaded_mb:.1f} MB / {total_mb:.1f} MB)"
                    }) + "\n"
                continue
            elif msg.startswith("DOWNLOAD_START:"):
                yield json.dumps({
                    "type": "progress",
                    "step": "downloading",
                    "percent": 0.0,
                    "message": f"Avvio download del modello '{model}' da Hugging Face..."
                }) + "\n"
                continue
            elif msg.startswith("DOWNLOAD_COMPLETE:"):
                yield json.dumps({
                    "type": "progress",
                    "step": "loading_model",
                    "percent": 100.0,
                    "message": "Download completato. Caricamento del modello in memoria..."
                }) + "\n"
                continue

            yield json.dumps({
                "type": "progress",
                "step": "transcribing",
                "message": msg
            }) + "\n"
        except queue.Empty:
            await asyncio.sleep(0.1)

    t.join()

    if transcribe_error:
        yield json.dumps({
            "type": "error",
            "message": f"Transcription failed: {transcribe_error}"
        }) + "\n"
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except OSError:
            pass
        return

    # Success payload formulation
    elapsed = time.perf_counter() - started_at
    logger.info(f"[Transcriber] Total processing time (streaming): {elapsed:.2f} seconds")
    asr_metadata = public_asr_metadata(asr_provider, model, provider_options or {})
    if backend:
        asr_metadata["backend"] = backend
    
    payload = {
        "text": transcribe_result.get("text", ""),
        "language": transcribe_result.get("language", language),
        "segments": transcribe_result.get("segments", []),
        "metadata": transcribe_result.get("metadata", {}),
        "model": asr_metadata["model"],
        "backend": asr_metadata["backend"],
        "asr_provider": asr_metadata["asr_provider"],
        "provider_options": asr_metadata["provider_options"],
        "recording_id": recording_id or "",
        "stats": {
            "time_total_seconds": elapsed,
            **asr_metadata,
        },
    }
    payload = _clean_nan_values(payload)
    try:
        if payload_postprocessor is not None:
            yield json.dumps({
                "type": "progress",
                "step": "diarizing",
                "message": "Separazione degli speaker..."
            }) + "\n"
            payload = payload_postprocessor(Path(audio_path), payload)
        save_cached_result(cache_key, payload)

        saved_meta = transcription_store.save(payload, audio_filename=audio_filename, recording_id=recording_id)
        payload["saved_id"] = saved_meta["id"]
        payload["saved_file_path"] = str(transcription_store.root)

        yield json.dumps({
            "type": "completed",
            "data": payload
        }) + "\n"
    except Exception as exc:
        logger.error("[Transcriber] Post-processing failed: %s", exc, exc_info=True)
        yield json.dumps({
            "type": "error",
            "message": f"Transcription post-processing failed: {exc}",
        }) + "\n"
    finally:
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
                logger.info(f"[Transcriber] Cleaned up temporary file: {audio_path}")
        except OSError as exc:
            logger.warning(f"[Transcriber] Failed to remove temp file {audio_path}: {exc}")
