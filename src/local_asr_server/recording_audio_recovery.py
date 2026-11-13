"""Validate native checkpoints and build a new WAV without modifying originals.

RecordingStore is the persistence owner. This module only interprets the native
segment format; it never changes metadata, starts capture, or deletes sources.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import wave


class AudioRecoveryError(RuntimeError):
    pass


def _directory(session: Path, source: str) -> Path:
    if source not in {"mic", "system"}:
        raise AudioRecoveryError("Invalid recovery source")
    root = session / ".audio-recovery"
    directory = root / source
    if root.is_symlink() or directory.is_symlink():
        raise AudioRecoveryError("Recovery directory must not be a symlink")
    return directory


def has_checkpoints(session: Path, source: str) -> bool:
    if source not in {"mic", "system"}:
        return False
    directory = _directory(session, source)
    return (directory / "00000000.json").is_file()


def _read_file(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise AudioRecoveryError("Oversized recovery checkpoint")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise AudioRecoveryError("Oversized recovery checkpoint")
    return data


def _file_digest(path: Path) -> tuple[int, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32000 * 86400 + 1024:
            raise AudioRecoveryError("Recovery output must be a regular file")
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return info.st_size, digest.hexdigest()


def _manifests(directory: Path) -> list[Path]:
    manifests = []
    for manifest in directory.glob('????????.json'):
        manifests.append(manifest)
        if len(manifests) > 86400:
            raise AudioRecoveryError('Too many recovery checkpoints')
    return sorted(manifests)


def _verified_segments(directory: Path, source: str, manifests: list[Path]):
    frames = 0
    previous_end: float | None = None
    padded_frames = 0
    for index, manifest_path in enumerate(manifests):
        if manifest_path.name != f"{index:08d}.json":
            raise AudioRecoveryError("Non-contiguous recovery checkpoints")
        raw_manifest = _read_file(manifest_path, 4096)
        manifest = json.loads(raw_manifest)
        if not isinstance(manifest, dict):
            raise AudioRecoveryError("Invalid recovery manifest")
        if (type(manifest.get("version")) is not int or manifest["version"] != 1 or manifest.get("source") != source
                or type(manifest.get("sequence")) is not int or manifest["sequence"] != index
                or manifest.get("file") != f"{index:08d}.wav"):
            raise AudioRecoveryError("Invalid recovery manifest")
        audio = directory / f"{index:08d}.wav"
        data = _read_file(audio, 4 * 1024 * 1024)
        if (type(manifest.get("bytes")) is not int or manifest["bytes"] != len(data)
                or manifest.get("sha256") != hashlib.sha256(data).hexdigest()):
            raise AudioRecoveryError("Recovery checkpoint checksum mismatch")
        # Feed only validated bytes to wave: do not reopen a mutable path.
        with wave.open(io.BytesIO(data), "rb") as segment:
            if (segment.getnchannels(), segment.getsampwidth(), segment.getframerate(), segment.getcomptype()) != (1, 2, 16000, "NONE"):
                raise AudioRecoveryError("Unsupported recovery audio format")
            count = segment.getnframes()
            pcm = segment.readframes(count)
            if count <= 0 or len(pcm) != count * 2:
                raise AudioRecoveryError("Truncated recovery audio")
            if ('frames' in manifest and (type(manifest['frames']) is not int or manifest['frames'] != count)) or (
                    'total_frames' in manifest and (type(manifest['total_frames']) is not int or manifest['total_frames'] != frames + count)):
                raise AudioRecoveryError('Recovery frame horizon does not match audio')
            # Checkpoint timing is retained to detect a missing interval;
            # concatenation must not disguise gaps as continuous audio.
            if any(type(manifest.get(key)) not in (int, float) for key in ('start_pts', 'end_pts')):
                raise AudioRecoveryError("Invalid recovery timing")
            start = float(manifest['start_pts'])
            end = float(manifest['end_pts'])
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                raise AudioRecoveryError("Invalid recovery timing")
            if abs(end - start - count / 16000) > .02:
                raise AudioRecoveryError("Recovery timing does not match audio frames")
            discontinuity = manifest.get('discontinuity_before', False)
            if type(discontinuity) is not bool:
                raise AudioRecoveryError("Invalid recovery discontinuity marker")
            gap_frames = 0
            if previous_end is not None:
                difference = start - previous_end
                if difference < -(1 / 16000 + 0.001):
                    raise AudioRecoveryError("Recovery clocks overlapped or moved backwards")
                if difference > 1 / 16000 + 0.001:
                    # A missing interval is acceptable only after the native
                    # source owner explicitly sealed a device switch. Silence
                    # in the derivative reserves time; it is NOT captured speech.
                    if discontinuity is not True:
                        raise AudioRecoveryError("Unacknowledged recovery audio gap")
                    gap_frames = round(difference * 16000)
                    if gap_frames > 16000 * 86400:
                        raise AudioRecoveryError("Recovery gap exceeds one-day bound")
            previous_end = end
            frames += count
            padded_frames += gap_frames
            if frames + padded_frames > 16000 * 86400:
                raise AudioRecoveryError("Recovery audio exceeds one-day bound")
        yield pcm, raw_manifest, data, gap_frames


def checkpoint_frame_count(session: Path, source: str) -> int:
    """Count actual verified samples, never trust an unverified JSON horizon."""
    directory = _directory(session, source)
    try:
        return sum(len(pcm) // 2 + gap for pcm, _, _, gap in _verified_segments(directory, source, _manifests(directory)))
    except (OSError, ValueError, KeyError, TypeError, wave.Error) as exc:
        raise AudioRecoveryError("Invalid recovery frame horizon") from exc


def recover_checkpoint_audio(session: Path, source: str) -> Path | None:
    """Recover only a contiguous verified prefix; leave all input bytes intact.

    The incomplete final segment and any audio without a commit manifest are
    retained as evidence, never silently promoted. A gap/corrupt committed pair
    fails closed instead of publishing an apparently complete recording.
    """
    directory = _directory(session, source)
    if not directory.exists():
        return None
    # Eight digits, at most one day of one-second checkpoints per source.
    manifests = _manifests(directory)
    if not manifests:
        return None
    digest = hashlib.sha256()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{source}.recovery-", suffix=".wav", dir=session)
    temporary = Path(temporary_name)
    os.close(fd)
    try:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            for pcm, manifest, data, gap in _verified_segments(directory, source, manifests):
                # Keep playback/ASR offsets aligned with the source timeline.
                # The original checkpoints stay immutable and the persisted
                # source_interruption events explicitly identify missing audio.
                if gap:
                    silence = b"\x00\x00" * 8192
                    while gap:
                        batch = min(gap, 8192)
                        output.writeframesraw(silence[:batch * 2])
                        gap -= batch
                output.writeframesraw(pcm)
                digest.update(manifest)
                digest.update(data)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        # Content-derived names and exclusive publication make retry idempotent;
        # original mic.wav/system.wav and all checkpoints remain untouched.
        target = session / f"{source}.recovered-{digest.hexdigest()}.wav"
        try:
            os.link(temporary, target)
        except FileExistsError:
            if _file_digest(target) != _file_digest(temporary):
                raise AudioRecoveryError("Existing recovery output differs")
        directory_fd = os.open(session, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return target
    except (OSError, ValueError, KeyError, TypeError, wave.Error) as exc:
        raise AudioRecoveryError("Unable to reconstruct verified recovery audio") from exc
    finally:
        temporary.unlink(missing_ok=True)
