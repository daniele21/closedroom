from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_asr_server.catalog import CatalogStore
logger = logging.getLogger("uvicorn.error")

from local_asr_server.visual_intelligence.contracts import (
    MAX_VISUAL_FRAME_BYTES,
    VISUAL_DOCUMENT_FILE,
    VISUAL_OBSERVATIONS_FILE,
    VISUAL_PROCESSING_CHECKPOINT,
    VISUAL_GENERATION_STAGING_DIR,
    VISUAL_RECOVERY_TTL_SECONDS,
    VISUAL_ROUTING_FILE,
    VISUAL_SUMMARY_FILE,
)


VALID_STATUSES = {
    "recording",
    "finalizing",
    "recorded",
    "interrupted",
    "recoverable",
    "transcribing",
    "completed",
    "failed",
}

VALID_CAPTURE_MODES = {"both", "mic_only", "pc_only", "legacy_mixed"}
VALID_TRACK_IDS = {"mixed", "mic", "system"}

SCREENSHOT_MANIFEST_VERSION = 1
MAX_SCREENSHOT_BYTES = 25 * 1024 * 1024
MAX_SCREENSHOT_THUMBNAIL_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOT_PIXELS = 100_000_000
MAX_SCREENSHOTS_PER_RECORDING = 200
MIN_SCREENSHOT_FREE_BYTES = 32 * 1024 * 1024

TRACK_LABELS = {
    "mixed": "Conversazione",
    "mic": "Tu",
    "system": "Computer",
}

TRACK_SOURCES = {
    "mixed": "mixed",
    "mic": "mic",
    "system": "system",
}


class RecordingError(Exception):
    pass


class RecordingNotFound(RecordingError):
    pass


class RecordingConflict(RecordingError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extension_for_mime(mime_type: str) -> str:
    normalized = mime_type.lower()
    if "ogg" in normalized:
        return ".ogg"
    if "mp4" in normalized or "m4a" in normalized:
        return ".m4a"
    if "wav" in normalized:
        return ".wav"
    return ".webm"


class RecordingStore:
    def __init__(
        self,
        default_root: Path,
        use_settings_dir: bool = True,
        catalog: CatalogStore | None = None,
    ):
        self._default_root = default_root.expanduser().resolve()
        self._use_settings_dir = use_settings_dir
        self.catalog = catalog
        # Verify write permission on current root
        curr_root = self.root
        curr_root.mkdir(parents=True, exist_ok=True)
        if not os.access(curr_root, os.W_OK):
            raise PermissionError(f"Recording directory is not writable: {curr_root}")
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._mark_interrupted_jobs()
        self._reconcile_screenshot_assets()
        self.sync_catalog()
        self.cleanup_orphaned_visual_processing()

    @property
    def root(self) -> Path:
        if self._use_settings_dir:
            from local_asr_server.settings import load_settings
            settings = load_settings()
            path_str = settings.get("recordings_dir")
            if path_str:
                path = Path(path_str).expanduser().resolve()
                path.mkdir(parents=True, exist_ok=True)
                return path
        path = self._default_root
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(
        self,
        *,
        title: str,
        project_name: str | None = None,
        mime_type: str,
        model: str,
        language: str | None,
        capture_mode: str = "legacy_mixed",
        capture_backend: str = "browser",
    ) -> dict[str, Any]:
        recording_id = str(uuid.uuid4())
        date_dir = datetime.now(timezone.utc).date().isoformat()
        session_dir = self.root / date_dir / recording_id
        session_dir.mkdir(parents=True)
        extension = _extension_for_mime(mime_type)
        if capture_mode not in VALID_CAPTURE_MODES:
            raise RecordingConflict(f"Invalid capture mode: {capture_mode}")
        track_ids = self._track_ids_for_mode(capture_mode)
        primary_track_id = self._primary_track_id_for_mode(capture_mode)
        audio_tracks = [
            {
                "id": track_id,
                "source": TRACK_SOURCES[track_id],
                "label": TRACK_LABELS[track_id],
                "mime_type": mime_type,
                "extension": extension,
                "chunk_count": 0,
                "bytes_written": 0,
                "chunks": [],
                "primary": track_id == primary_track_id,
                "audio_file": None,
            }
            for track_id in track_ids
        ]
        default_title = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata = {
            "id": recording_id,
            "title": title.strip()[:200] if title.strip() else default_title,
            "project_name": (project_name or "").strip()[:200],
            "status": "recording",
            "created_at": _utc_now(),
            "stopped_at": None,
            "completed_at": None,
            "mime_type": mime_type,
            "extension": extension,
            "chunk_count": 0,
            "bytes_written": 0,
            "model": model,
            "language": language,
            "error": None,
            "relative_dir": str(session_dir.relative_to(self.root)),
            "capture_mode": capture_mode,
            "capture_backend": capture_backend,
            "capture_status": "idle",
            "timeline": None,
            "quality_report": None,
            "warnings": [],
            "primary_track_id": primary_track_id,
            "audio_tracks": audio_tracks,
            "screenshot_count": 0,
            "screenshot_manifest_version": SCREENSHOT_MANIFEST_VERSION,
            "screenshot_revision": 0,
        }
        for track in audio_tracks:
            self._track_part_path(session_dir, track).touch()
        self._write_metadata(session_dir, metadata)
        self._upsert_catalog(metadata)
        return self.public_metadata(metadata)

    def update(self, recording_id: str, title: str | None = None, project_name: str | None = None) -> dict[str, Any]:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            if title is not None:
                new_title = title.strip()[:200]
                if not new_title:
                    try:
                        dt = datetime.fromisoformat(metadata["created_at"])
                        new_title = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        new_title = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                metadata["title"] = new_title
            if project_name is not None:
                metadata["project_name"] = project_name.strip()[:200]
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self.public_metadata(metadata)

    def update_title(self, recording_id: str, title: str) -> dict[str, Any]:
        return self.update(recording_id, title=title)

    def append_chunk(
        self,
        recording_id: str,
        sequence: int,
        content: bytes,
        *,
        sha256: str | None = None,
        size: int | None = None,
        client_started_at_ms: float | None = None,
        client_chunk_start_ms: float | None = None,
        client_chunk_end_ms: float | None = None,
    ) -> dict[str, Any]:
        return self.append_track_chunk(
            recording_id,
            "mixed",
            sequence,
            content,
            sha256=sha256,
            size=size,
            client_started_at_ms=client_started_at_ms,
            client_chunk_start_ms=client_chunk_start_ms,
            client_chunk_end_ms=client_chunk_end_ms,
        )

    def append_track_chunk(
        self,
        recording_id: str,
        track_id: str,
        sequence: int,
        content: bytes,
        *,
        sha256: str | None = None,
        size: int | None = None,
        client_started_at_ms: float | None = None,
        client_chunk_start_ms: float | None = None,
        client_chunk_end_ms: float | None = None,
    ) -> dict[str, Any]:
        if sequence < 0:
            raise RecordingConflict("Chunk sequence must be non-negative")
        if not content:
            raise RecordingConflict("Chunk is empty")
        content_hash = hashlib.sha256(content).hexdigest()
        if sha256 and sha256.lower() != content_hash:
            raise RecordingConflict("Chunk checksum does not match uploaded content")
        if size is not None and size != len(content):
            raise RecordingConflict("Chunk size does not match uploaded content")

        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            metadata = self._ensure_tracks(metadata)
            if metadata["status"] != "recording":
                raise RecordingConflict("Recording is no longer accepting chunks")
            track = self._track_for(metadata, track_id)
            expected = track["chunk_count"]
            chunks = self._track_chunks(track)
            if sequence < expected:
                existing = next((item for item in chunks if item.get("sequence") == sequence), None)
                if (
                    existing
                    and existing.get("sha256") == content_hash
                    and existing.get("size") == len(content)
                ):
                    return self.public_metadata(metadata)
                raise RecordingConflict(
                    f"Chunk sequence {sequence} was already committed with different content"
                )
            if sequence != expected:
                raise RecordingConflict(
                    f"Expected chunk sequence {expected}, received {sequence}"
                )

            part_path = self._track_part_path(session_dir, track)
            with part_path.open("ab") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())

            track["chunk_count"] += 1
            track["bytes_written"] += len(content)
            chunks.append({
                "sequence": sequence,
                "sha256": content_hash,
                "size": len(content),
                "received_at": _utc_now(),
                "client_started_at_ms": client_started_at_ms,
                "client_chunk_start_ms": client_chunk_start_ms,
                "client_chunk_end_ms": client_chunk_end_ms,
            })
            self._sync_legacy_totals(metadata)
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self.public_metadata(metadata)

    def expected_sequence(self, recording_id: str, track_id: str) -> dict[str, Any]:
        session_dir, metadata = self._load(recording_id)
        metadata = self._ensure_tracks(metadata)
        track = self._track_for(metadata, track_id)
        return {
            "recording_id": recording_id,
            "track_id": track_id,
            "status": metadata["status"],
            "expected_sequence": track.get("chunk_count", 0),
            "last_committed_sequence": track.get("chunk_count", 0) - 1,
            "bytes_written": track.get("bytes_written", 0),
            "part_file_exists": self._track_part_path(session_dir, track).exists(),
            "audio_file_exists": self._track_audio_path(session_dir, track).exists(),
        }

    def session_dir(self, recording_id: str) -> Path:
        session_dir, _ = self._load(recording_id)
        return session_dir

    def mark_capture_started(self, recording_id: str, *, backend: str) -> dict[str, Any]:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            metadata["capture_backend"] = backend
            metadata["capture_status"] = "recording"
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self.public_metadata(metadata)

    def mark_capture_event(self, recording_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            timeline = metadata.get("timeline")
            if not isinstance(timeline, dict):
                timeline = {"events": []}
                metadata["timeline"] = timeline

            events = timeline.get("events")
            if not isinstance(events, list):
                events = []
                timeline["events"] = events
            events.append(event)

            if event.get("type") == "warning":
                warnings = metadata.get("warnings")
                if not isinstance(warnings, list):
                    warnings = []
                    metadata["warnings"] = warnings
                warnings.append(event.get("message") or event.get("reason") or "capture_warning")
            if event.get("type") == "error":
                metadata["capture_status"] = "error"
                warnings = metadata.get("warnings")
                if not isinstance(warnings, list):
                    warnings = []
                    metadata["warnings"] = warnings
                warnings.append(event.get("message") or "capture_error")
            self._write_timeline(session_dir, metadata)
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self.public_metadata(metadata)

    def save_quality_report(self, recording_id: str, report: dict[str, Any]) -> dict[str, Any]:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            metadata["quality_report"] = report
            metadata["warnings"] = sorted(set((metadata.get("warnings") or []) + (report.get("warnings") or [])))
            self._write_json_atomic(session_dir / "quality_report.json", report)
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self.public_metadata(metadata)

    def save_intelligence(self, recording_id: str, intelligence: dict[str, Any]) -> dict[str, Any]:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            self._write_json_atomic(session_dir / "intelligence.json", intelligence)
            return self.public_metadata(metadata)


    def screenshot_for_request(self, recording_id: str, request_id: str) -> dict[str, Any] | None:
        request_id = request_id.strip()
        if not request_id:
            return None
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            manifest = self._read_screenshot_manifest(session_dir, recording_id)
            item = next((entry for entry in manifest["items"] if entry.get("request_id") == request_id), None)
            return self._public_screenshot(session_dir, item) if item is not None else None

    def reserve_screenshot_capture(
        self,
        recording_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        """Reserve RecordingStore-owned staging paths for one manual screenshot."""
        request_id = request_id.strip()
        if not request_id or len(request_id) > 128:
            raise RecordingConflict("Invalid screenshot request_id")
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            if metadata["status"] != "recording":
                raise RecordingConflict("Screenshots can only be captured while recording")
            manifest = self._read_screenshot_manifest(session_dir, recording_id)
            existing = next(
                (entry for entry in manifest["items"] if entry.get("request_id") == request_id),
                None,
            )
            if existing is not None:
                return {
                    "existing": self._public_screenshot(session_dir, existing),
                    "token": None,
                    "original_path": None,
                    "thumbnail_path": None,
                }
            if len(manifest["items"]) >= MAX_SCREENSHOTS_PER_RECORDING:
                raise RecordingConflict(
                    f"Screenshot limit reached ({MAX_SCREENSHOTS_PER_RECORDING} per recording)"
                )
            if shutil.disk_usage(session_dir).free < MIN_SCREENSHOT_FREE_BYTES:
                raise OSError("Insufficient disk space to capture screenshot")

            staging_dir = session_dir / ".screenshot-capture-temp"
            staging_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            original_path, thumbnail_path = self._screenshot_staging_paths(session_dir, token)
            original_path.unlink(missing_ok=True)
            thumbnail_path.unlink(missing_ok=True)
            return {
                "existing": None,
                "token": token,
                "original_path": original_path,
                "thumbnail_path": thumbnail_path,
            }

    def discard_screenshot_capture(self, recording_id: str, token: str | None) -> None:
        if not token:
            return
        try:
            uuid.UUID(hex=token)
        except (ValueError, AttributeError):
            return
        try:
            with self._lock_for(recording_id):
                session_dir, _ = self._load(recording_id)
                original_path, thumbnail_path = self._screenshot_staging_paths(session_dir, token)
                original_path.unlink(missing_ok=True)
                thumbnail_path.unlink(missing_ok=True)
                try:
                    original_path.parent.rmdir()
                except OSError:
                    pass
        except RecordingNotFound:
            return

    def commit_screenshot_capture(
        self,
        recording_id: str,
        *,
        request_id: str,
        token: str,
        capture: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically promote worker-written staging assets without copying them through Python RAM."""
        request_id = request_id.strip()
        if not request_id or len(request_id) > 128:
            raise RecordingConflict("Invalid screenshot request_id")
        try:
            parsed_token = uuid.UUID(hex=token)
        except (ValueError, AttributeError) as exc:
            raise RecordingConflict("Invalid screenshot staging token") from exc
        token = parsed_token.hex

        width = int(capture.get("width") or 0)
        height = int(capture.get("height") or 0)
        if width <= 0 or height <= 0 or width * height > MAX_SCREENSHOT_PIXELS:
            raise RecordingConflict("Screenshot dimensions are invalid or exceed the pixel limit")
        timestamp = float(capture.get("timestamp") or 0.0)
        captured_uptime = float(capture.get("captured_uptime") or 0.0)
        if timestamp < 0 or captured_uptime <= 0:
            raise RecordingConflict("Screenshot capture timestamp is invalid")

        persist_started = time.monotonic()
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            if metadata["status"] != "recording":
                raise RecordingConflict("Screenshots can only be captured while recording")
            original_staging, thumbnail_staging = self._screenshot_staging_paths(session_dir, token)
            if not original_staging.is_file() or not thumbnail_staging.is_file():
                raise RecordingConflict("Screenshot staging assets are missing")

            original_size = original_staging.stat().st_size
            thumbnail_size = thumbnail_staging.stat().st_size
            if original_size <= 0 or original_size > MAX_SCREENSHOT_BYTES:
                raise RecordingConflict("Screenshot original must be a JPEG no larger than 25 MB")
            if thumbnail_size <= 0 or thumbnail_size > MAX_SCREENSHOT_THUMBNAIL_BYTES:
                raise RecordingConflict("Screenshot thumbnail must be a JPEG no larger than 2 MB")
            with original_staging.open("rb") as handle:
                if handle.read(3) != b"\xff\xd8\xff":
                    raise RecordingConflict("Screenshot original must be JPEG")
            with thumbnail_staging.open("rb") as handle:
                if handle.read(3) != b"\xff\xd8\xff":
                    raise RecordingConflict("Screenshot thumbnail must be JPEG")

            manifest = self._read_screenshot_manifest(session_dir, recording_id)
            existing = next(
                (entry for entry in manifest["items"] if entry.get("request_id") == request_id),
                None,
            )
            if existing is not None:
                original_staging.unlink(missing_ok=True)
                thumbnail_staging.unlink(missing_ok=True)
                return self._public_screenshot(session_dir, existing)
            if len(manifest["items"]) >= MAX_SCREENSHOTS_PER_RECORDING:
                raise RecordingConflict(
                    f"Screenshot limit reached ({MAX_SCREENSHOTS_PER_RECORDING} per recording)"
                )
            if shutil.disk_usage(session_dir).free < MIN_SCREENSHOT_FREE_BYTES:
                raise OSError("Insufficient disk space to persist screenshot")

            digest = hashlib.sha256()
            with original_staging.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)

            sequence = max(
                (int(entry.get("sequence") or -1) for entry in manifest["items"]),
                default=-1,
            ) + 1
            screenshot_id = str(uuid.uuid4())
            screenshots_dir = self._screenshots_dir(session_dir)
            screenshots_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            original_name = f"screenshot-{sequence:04d}-{screenshot_id}.jpg"
            thumbnail_name = f"screenshot-{sequence:04d}-{screenshot_id}-thumb.jpg"
            original_path = screenshots_dir / original_name
            thumbnail_path = screenshots_dir / thumbnail_name

            os.replace(str(original_staging), str(original_path))
            try:
                os.replace(str(thumbnail_staging), str(thumbnail_path))
            except Exception:
                original_path.unlink(missing_ok=True)
                raise

            persist_ms = int((time.monotonic() - persist_started) * 1000.0)
            entry = {
                "screenshot_id": screenshot_id,
                "recording_id": recording_id,
                "request_id": request_id,
                "sequence": sequence,
                "capture_kind": "manual",
                "timestamp": timestamp,
                "captured_uptime": captured_uptime,
                "captured_wall_time": capture.get("captured_wall_time"),
                "recording_ready_uptime": capture.get("recording_ready_uptime"),
                "display_id": int(capture.get("display_id") or 0),
                "display_title": capture.get("display_title"),
                "format": "image/jpeg",
                "width": width,
                "height": height,
                "thumbnail_width": int(capture.get("thumbnail_width") or 0),
                "thumbnail_height": int(capture.get("thumbnail_height") or 0),
                "bytes": original_size,
                "thumbnail_bytes": thumbnail_size,
                "sha256": digest.hexdigest(),
                "original_file": original_name,
                "thumbnail_file": thumbnail_name,
                "overlay_exclusion": capture.get("overlay_exclusion") or "unknown",
                "capture_ms": capture.get("capture_ms"),
                "encode_ms": capture.get("encode_ms"),
                "worker_write_ms": capture.get("write_ms"),
                "roundtrip_ms": capture.get("roundtrip_ms"),
                "persist_ms": persist_ms,
                "worker_restart_count": capture.get("worker_restart_count"),
                "created_at": _utc_now(),
            }
            manifest["items"].append(entry)
            self._write_json_atomic(self._screenshot_manifest_path(session_dir), manifest)
            metadata["screenshot_count"] = len(manifest["items"])
            metadata["screenshot_manifest_version"] = SCREENSHOT_MANIFEST_VERSION
            metadata["screenshot_revision"] = int(metadata.get("screenshot_revision") or 0) + 1
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self._public_screenshot(session_dir, entry)

    def save_screenshot(
        self,
        recording_id: str,
        *,
        request_id: str,
        capture: dict[str, Any],
        original: bytes,
        thumbnail: bytes,
    ) -> dict[str, Any]:
        request_id = request_id.strip()
        if not request_id or len(request_id) > 128:
            raise RecordingConflict("Invalid screenshot request_id")
        if not original or not original.startswith(b"\xff\xd8\xff") or len(original) > MAX_SCREENSHOT_BYTES:
            raise RecordingConflict("Screenshot original must be a JPEG no larger than 25 MB")
        if not thumbnail or not thumbnail.startswith(b"\xff\xd8\xff") or len(thumbnail) > MAX_SCREENSHOT_THUMBNAIL_BYTES:
            raise RecordingConflict("Screenshot thumbnail must be a JPEG no larger than 2 MB")

        width = int(capture.get("width") or 0)
        height = int(capture.get("height") or 0)
        if width <= 0 or height <= 0 or width * height > MAX_SCREENSHOT_PIXELS:
            raise RecordingConflict("Screenshot dimensions are invalid or exceed the pixel limit")
        timestamp = float(capture.get("timestamp") or 0.0)
        captured_uptime = float(capture.get("captured_uptime") or 0.0)
        if timestamp < 0 or captured_uptime <= 0:
            raise RecordingConflict("Screenshot capture timestamp is invalid")

        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            if metadata["status"] != "recording":
                raise RecordingConflict("Screenshots can only be captured while recording")
            manifest = self._read_screenshot_manifest(session_dir, recording_id)
            existing = next((entry for entry in manifest["items"] if entry.get("request_id") == request_id), None)
            if existing is not None:
                return self._public_screenshot(session_dir, existing)
            if len(manifest["items"]) >= MAX_SCREENSHOTS_PER_RECORDING:
                raise RecordingConflict(
                    f"Screenshot limit reached ({MAX_SCREENSHOTS_PER_RECORDING} per recording)"
                )

            required = len(original) + len(thumbnail) + MIN_SCREENSHOT_FREE_BYTES
            if shutil.disk_usage(session_dir).free < required:
                raise OSError("Insufficient disk space to persist screenshot")

            sequence = max((int(entry.get("sequence") or -1) for entry in manifest["items"]), default=-1) + 1
            screenshot_id = str(uuid.uuid4())
            screenshots_dir = self._screenshots_dir(session_dir)
            screenshots_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            original_name = f"screenshot-{sequence:04d}-{screenshot_id}.jpg"
            thumbnail_name = f"screenshot-{sequence:04d}-{screenshot_id}-thumb.jpg"
            original_path = screenshots_dir / original_name
            thumbnail_path = screenshots_dir / thumbnail_name
            self._write_bytes_atomic(original_path, original)
            try:
                self._write_bytes_atomic(thumbnail_path, thumbnail)
            except Exception:
                original_path.unlink(missing_ok=True)
                raise

            entry = {
                "screenshot_id": screenshot_id,
                "recording_id": recording_id,
                "request_id": request_id,
                "sequence": sequence,
                "capture_kind": "manual",
                "timestamp": timestamp,
                "captured_uptime": captured_uptime,
                "captured_wall_time": capture.get("captured_wall_time"),
                "recording_ready_uptime": capture.get("recording_ready_uptime"),
                "display_id": int(capture.get("display_id") or 0),
                "display_title": capture.get("display_title"),
                "format": "image/jpeg",
                "width": width,
                "height": height,
                "thumbnail_width": int(capture.get("thumbnail_width") or 0),
                "thumbnail_height": int(capture.get("thumbnail_height") or 0),
                "bytes": len(original),
                "thumbnail_bytes": len(thumbnail),
                "sha256": hashlib.sha256(original).hexdigest(),
                "original_file": original_name,
                "thumbnail_file": thumbnail_name,
                "overlay_exclusion": capture.get("overlay_exclusion") or "unknown",
                "created_at": _utc_now(),
            }
            manifest["items"].append(entry)
            self._write_json_atomic(self._screenshot_manifest_path(session_dir), manifest)
            metadata["screenshot_count"] = len(manifest["items"])
            metadata["screenshot_manifest_version"] = SCREENSHOT_MANIFEST_VERSION
            metadata["screenshot_revision"] = int(metadata.get("screenshot_revision") or 0) + 1
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self._public_screenshot(session_dir, entry)

    def list_screenshots(self, recording_id: str) -> list[dict[str, Any]]:
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            manifest = self._read_screenshot_manifest(session_dir, recording_id)
            return [
                self._public_screenshot(session_dir, item)
                for item in sorted(
                    manifest["items"],
                    key=lambda item: (float(item.get("timestamp") or 0.0), int(item.get("sequence") or 0)),
                )
            ]

    def screenshot_asset_path(self, recording_id: str, screenshot_id: str, *, thumbnail: bool = False) -> Path:
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            manifest = self._read_screenshot_manifest(session_dir, recording_id)
            item = next((entry for entry in manifest["items"] if entry.get("screenshot_id") == screenshot_id), None)
            if item is None:
                raise RecordingNotFound(screenshot_id)
            key = "thumbnail_file" if thumbnail else "original_file"
            screenshots_dir = self._screenshots_dir(session_dir).resolve()
            path = (screenshots_dir / str(item.get(key) or "")).resolve()
            if screenshots_dir not in path.parents or not path.is_file():
                raise RecordingNotFound(screenshot_id)
            return path

    def delete_screenshot(self, recording_id: str, screenshot_id: str) -> None:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            manifest = self._read_screenshot_manifest(session_dir, recording_id)
            item = next((entry for entry in manifest["items"] if entry.get("screenshot_id") == screenshot_id), None)
            if item is None:
                raise RecordingNotFound(screenshot_id)
            screenshots_dir = self._screenshots_dir(session_dir).resolve()
            for key in ("original_file", "thumbnail_file"):
                path = (screenshots_dir / str(item.get(key) or "")).resolve()
                if screenshots_dir in path.parents:
                    path.unlink(missing_ok=True)
            manifest["items"] = [entry for entry in manifest["items"] if entry.get("screenshot_id") != screenshot_id]
            self._write_json_atomic(self._screenshot_manifest_path(session_dir), manifest)
            metadata["screenshot_count"] = len(manifest["items"])
            metadata["screenshot_manifest_version"] = SCREENSHOT_MANIFEST_VERSION
            metadata["screenshot_revision"] = int(metadata.get("screenshot_revision") or 0) + 1
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)

    def _screenshot_staging_paths(self, session_dir: Path, token: str) -> tuple[Path, Path]:
        staging_dir = session_dir / ".screenshot-capture-temp"
        return (
            staging_dir / f"{token}.jpg",
            staging_dir / f"{token}-thumb.jpg",
        )

    def _screenshots_dir(self, session_dir: Path) -> Path:
        return session_dir / "screenshots"

    def _screenshot_manifest_path(self, session_dir: Path) -> Path:
        return self._screenshots_dir(session_dir) / "manifest.json"

    def _read_screenshot_manifest(self, session_dir: Path, recording_id: str) -> dict[str, Any]:
        manifest_path = self._screenshot_manifest_path(session_dir)
        if not manifest_path.exists():
            return {"schema_version": SCREENSHOT_MANIFEST_VERSION, "recording_id": recording_id, "items": []}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordingConflict("Screenshot manifest is unreadable") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RecordingConflict("Screenshot manifest is invalid")
        version = int(payload.get("schema_version") or SCREENSHOT_MANIFEST_VERSION)
        if version != SCREENSHOT_MANIFEST_VERSION:
            raise RecordingConflict(f"Unsupported screenshot manifest version: {version}")
        return {
            "schema_version": version,
            "recording_id": recording_id,
            "items": [item for item in payload["items"] if isinstance(item, dict)],
        }

    def _public_screenshot(self, session_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
        screenshots_dir = self._screenshots_dir(session_dir).resolve()
        original = (screenshots_dir / str(item.get("original_file") or "")).resolve()
        thumbnail = (screenshots_dir / str(item.get("thumbnail_file") or "")).resolve()
        original_ok = screenshots_dir in original.parents and original.is_file()
        thumbnail_ok = screenshots_dir in thumbnail.parents and thumbnail.is_file()
        return {
            key: value
            for key, value in item.items()
            if key not in {"original_file", "thumbnail_file"}
        } | {"available": original_ok, "thumbnail_available": thumbnail_ok}


    def list_visual_evidence_frames(self, recording_id: str) -> list[dict[str, Any]]:
        """Return post-meeting visual inputs with stable source provenance.

        Continuous visual frames keep their native sequence. Manual screenshots use
        a separate high sequence namespace so observation IDs cannot collide.
        """
        frames = [
            {
                **item,
                "evidence_source": "continuous_frame",
                "capture_kind": "automatic",
                "evidence_id": f"visual-frame-{int(item['sequence'])}",
            }
            for item in self.list_visual_frames(recording_id)
        ]
        screenshots = self.list_screenshots(recording_id)
        for item in screenshots:
            if not item.get("available"):
                frames.append({
                    "sequence": 1_000_000_000 + int(item.get("sequence") or 0),
                    "timestamp": float(item.get("timestamp") or 0.0),
                    "path": None,
                    "evidence_source": "manual_screenshot",
                    "capture_kind": "manual",
                    "evidence_id": item.get("screenshot_id"),
                    "screenshot_id": item.get("screenshot_id"),
                    "sha256": item.get("sha256"),
                    "display_id": item.get("display_id"),
                    "display_title": item.get("display_title"),
                    "available": False,
                })
                continue
            frames.append({
                "sequence": 1_000_000_000 + int(item.get("sequence") or 0),
                "timestamp": float(item.get("timestamp") or 0.0),
                "path": self.screenshot_asset_path(
                    recording_id, str(item["screenshot_id"]), thumbnail=False,
                ),
                "evidence_source": "manual_screenshot",
                "capture_kind": "manual",
                "evidence_id": item.get("screenshot_id"),
                "screenshot_id": item.get("screenshot_id"),
                "sha256": item.get("sha256"),
                "display_id": item.get("display_id"),
                "display_title": item.get("display_title"),
                "available": True,
            })
        return sorted(
            frames,
            key=lambda item: (float(item.get("timestamp") or 0.0), int(item.get("sequence") or 0)),
        )

    def stage_visual_frame(
        self, recording_id: str, sequence: int, timestamp: float, content: bytes,
    ) -> dict[str, Any]:
        if sequence < 0 or timestamp < 0 or not content:
            raise RecordingConflict("Invalid visual frame")
        if len(content) > MAX_VISUAL_FRAME_BYTES or not content.startswith(b"\xff\xd8\xff"):
            raise RecordingConflict("Visual frame must be a JPEG no larger than 5 MB")
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            if metadata["status"] != "recording":
                raise RecordingConflict("Visual frames can only be staged while recording")
            staging = session_dir / ".visual-staging"
            staging.mkdir(mode=0o700, parents=True, exist_ok=True)
            manifest = staging / "manifest.jsonl"
            if manifest.exists():
                lines = manifest.read_text(encoding="utf-8").splitlines()
                if lines:
                    previous = json.loads(lines[-1])
                    if sequence <= int(previous["sequence"]) or timestamp < float(previous["timestamp"]):
                        raise RecordingConflict("Visual frame sequence and timestamp must be monotonic")
            path = staging / f"frame-{sequence:08d}.jpg"
            if path.exists():
                raise RecordingConflict(f"Visual frame sequence already exists: {sequence}")
            self._write_bytes_atomic(path, content)
            with manifest.open("a", encoding="utf-8") as output:
                output.write(json.dumps({"sequence": sequence, "timestamp": timestamp, "file": path.name}) + "\n")
                output.flush()
                os.fsync(output.fileno())
            return {"sequence": sequence, "timestamp": timestamp, "bytes": len(content)}

    def list_visual_frames(self, recording_id: str) -> list[dict[str, Any]]:
        session_dir, _ = self._load(recording_id)
        staging = session_dir / ".visual-staging"
        manifest = staging / "manifest.jsonl"
        if not manifest.exists():
            return []
        frames = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            path = (staging / str(item.get("file") or "")).resolve()
            if path.parent == staging.resolve() and path.is_file():
                frames.append({**item, "path": path})
        return sorted(frames, key=lambda item: int(item["sequence"]))

    def reset_visual_observations(self, recording_id: str) -> None:
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            observations_path = session_dir / VISUAL_OBSERVATIONS_FILE
            if observations_path.exists():
                observations_path.unlink()

    def append_visual_observation(self, recording_id: str, observation: dict[str, Any]) -> None:
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            observations_path = session_dir / VISUAL_OBSERVATIONS_FILE
            # Append observation
            with observations_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(observation, ensure_ascii=False) + "\n")

    def save_visual_routing(self, recording_id: str, routing: dict[str, Any]) -> None:
        """Persist explainable frame-routing decisions without bloating catalog metadata."""
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            self._write_json_atomic(session_dir / VISUAL_ROUTING_FILE, routing)

    def reset_visual_routing(self, recording_id: str) -> None:
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            routing_path = session_dir / VISUAL_ROUTING_FILE
            if routing_path.exists():
                routing_path.unlink()

    def begin_visual_processing(
        self, recording_id: str, fingerprint: str, *, prompt_version: int | None = None,
    ) -> list[dict[str, Any]]:
        """Start a v2 run or resume successful candidates left by a process crash."""
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            checkpoint_path = session_dir / VISUAL_PROCESSING_CHECKPOINT
            observations_path = session_dir / VISUAL_OBSERVATIONS_FILE
            checkpoint = None
            if checkpoint_path.exists():
                try:
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    checkpoint = None
            if checkpoint and checkpoint.get("fingerprint") == fingerprint:
                return self._validated_recovered_observations(
                    self._read_valid_jsonl(observations_path), checkpoint,
                )
            self._write_text_atomic(observations_path, "")
            self._write_json_atomic(checkpoint_path, {
                "schema_version": 1,
                "status": "running",
                "fingerprint": fingerprint,
                "prompt_version": prompt_version,
                "updated_at": _utc_now(),
            })
            return []

    @staticmethod
    def _validated_recovered_observations(items, checkpoint):
        valid_tasks = {"meeting_ui", "meeting_state", "shared_content"}
        recovered = []
        seen = set()
        for item in items:
            task = item.get("task")
            observation_id = item.get("observation_id")
            expected_id = f"visual-{item.get('sequence')}-{task}"
            if (
                item.get("schema_version") != 2
                or task not in valid_tasks
                or item.get("prompt_version") != checkpoint.get("prompt_version")
                or observation_id != expected_id
                or observation_id in seen
            ):
                continue
            seen.add(observation_id)
            recovered.append(item)
        return recovered

    def finish_visual_processing(self, recording_id: str) -> None:
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            checkpoint_path = session_dir / VISUAL_PROCESSING_CHECKPOINT
            if checkpoint_path.exists():
                checkpoint_path.unlink()

    def mark_visual_processing_retryable(self, recording_id: str, reason: str) -> None:
        """Keep visual staging resumable and eligible for TTL cleanup after backend failure."""
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            checkpoint_path = session_dir / VISUAL_PROCESSING_CHECKPOINT
            checkpoint: dict[str, Any] = {}
            if checkpoint_path.exists():
                try:
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    checkpoint = {}
            self._write_json_atomic(checkpoint_path, {
                **checkpoint,
                "schema_version": 1,
                "status": "retryable_failure",
                "reason": reason,
                "updated_at": _utc_now(),
            })

    @staticmethod
    def _read_valid_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        items = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                items.append(item)
        return items

    def replace_visual_intelligence_artifacts(
        self, recording_id: str, observations: list[dict[str, Any]], summary: dict[str, Any],
        document: dict[str, Any] | None = None, routing: dict[str, Any] | None = None,
        run_config: dict[str, Any] | None = None, trace_path: Path | None = None,
    ) -> None:
        """Stage and promote one coherent terminal visual generation, storing history under visual-runs."""
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            generation_id = str(
                summary.get("generation_id") or uuid.uuid4()
            )
            summary = {**summary, "generation_id": generation_id}
            
            # 1. Create staging directory for this run
            staging = session_dir / VISUAL_GENERATION_STAGING_DIR / generation_id
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(mode=0o700, parents=True)
            
            # 2. Write observations.jsonl to run folder (streaming)
            observations_file = staging / "observations.jsonl"
            with open(observations_file, "w", encoding="utf-8") as f:
                for item in observations:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
            # 3. Write run.json
            if run_config:
                self._write_json_atomic(staging / "run.json", run_config)
            
            # 4. Write routing.jsonl and routing_summary.json
            if routing:
                routing = {**routing, "generation_id": generation_id}
                routing_file = staging / "routing.jsonl"
                candidates = routing.get("candidates") or []
                with open(routing_file, "w", encoding="utf-8") as f:
                    for c in candidates:
                        f.write(json.dumps(c, ensure_ascii=False) + "\n")
                routing_summary = {k: v for k, v in routing.items() if k != "candidates"}
                self._write_json_atomic(staging / "routing_summary.json", routing_summary)
            
            # 5. Write trace.jsonl
            if trace_path and trace_path.exists():
                try:
                    shutil.copy(trace_path, staging / "trace.jsonl")
                except Exception as e:
                    logger.warning("Failed to copy trace file to staging: %s", e)
            
            # 6. Write result.json and metrics.json
            if document:
                clean_doc = {**document, "generation_id": generation_id, "observations": []}
                clean_doc["observation_store"] = "observations.jsonl"
                clean_doc["observation_count"] = len(observations)
                self._write_json_atomic(staging / "result.json", clean_doc)
            
            metrics = {
                "elapsed_seconds": summary.get("elapsed_seconds"),
                "frame_count": summary.get("frame_count"),
                "observation_count": len(observations),
                "parse_errors": summary.get("parse_errors"),
                "status": summary.get("status"),
            }
            self._write_json_atomic(staging / "metrics.json", metrics)
            
            # 7. Write compatibility files to staging first
            self._write_json_atomic(staging / VISUAL_SUMMARY_FILE, summary)
            serialized = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in observations)
            self._write_text_atomic(staging / VISUAL_OBSERVATIONS_FILE, serialized)
            if document:
                clean_doc = {**document, "generation_id": generation_id}
                self._write_json_atomic(staging / VISUAL_DOCUMENT_FILE, clean_doc)
            if routing:
                self._write_json_atomic(staging / VISUAL_ROUTING_FILE, routing)
                
            self._write_json_atomic(staging / "current_visual_generation.json", {
                "generation_id": generation_id,
                "created_at": time.time(),
                "model": summary.get("model"),
                "status": summary.get("status"),
            })
            
            # 8. Promote staging files to target visual-runs directory and root directory using os.replace
            run_dir = session_dir / "visual-runs" / generation_id
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir(mode=0o700, parents=True)
            
            compat_filenames = {
                VISUAL_SUMMARY_FILE,
                VISUAL_OBSERVATIONS_FILE,
                VISUAL_DOCUMENT_FILE,
                VISUAL_ROUTING_FILE,
                "current_visual_generation.json"
            }
            
            ordered_compat_names = [
                VISUAL_OBSERVATIONS_FILE,
                VISUAL_SUMMARY_FILE,
                VISUAL_DOCUMENT_FILE,
                VISUAL_ROUTING_FILE,
                "current_visual_generation.json"
            ]
            
            # Promote compat files first deterministically
            for name in ordered_compat_names:
                source = staging / name
                target = session_dir / name
                if source.exists():
                    os.replace(str(source), str(target))
                else:
                    target.unlink(missing_ok=True)
            
            # Promote non-compat files second
            for item in list(staging.iterdir()):
                if item.name in compat_filenames:
                    continue
                target = run_dir / item.name
                if item.is_dir():
                    target.mkdir(mode=0o700, parents=True)
                    for subitem in list(item.iterdir()):
                        os.replace(str(subitem), str(target / subitem.name))
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    os.replace(str(item), str(target))
            
            metadata["visual_intelligence"] = summary
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            shutil.rmtree(session_dir / VISUAL_GENERATION_STAGING_DIR, ignore_errors=True)

    def cleanup_orphaned_visual_processing(self, *, now: float | None = None) -> int:
        """Remove expired processing state without deleting captured meeting frames."""
        now = time.time() if now is None else now
        removed = 0
        if not self.root.exists():
            return removed
        for checkpoint in self.root.glob(f"*/*/{VISUAL_PROCESSING_CHECKPOINT}"):
            try:
                age = now - checkpoint.stat().st_mtime
            except OSError:
                continue
            if age <= VISUAL_RECOVERY_TTL_SECONDS:
                continue
            session_dir = checkpoint.parent
            checkpoint.unlink(missing_ok=True)
            shutil.rmtree(session_dir / VISUAL_GENERATION_STAGING_DIR, ignore_errors=True)
            removed += 1
        for staging in self.root.glob(f"*/*/{VISUAL_GENERATION_STAGING_DIR}"):
            try:
                age = now - staging.stat().st_mtime
            except OSError:
                continue
            if age > VISUAL_RECOVERY_TTL_SECONDS:
                shutil.rmtree(staging, ignore_errors=True)
                removed += 1
        return removed

    def save_visual_intelligence(
        self, recording_id: str, observations: list[dict[str, Any]], summary: dict[str, Any],
        document: dict[str, Any] | None = None,
    ) -> None:
        """Backward-compatible wrapper; new code should replace the complete set."""
        self.replace_visual_intelligence_artifacts(
            recording_id, observations, summary, document=document,
        )

    def get_visual_intelligence(self, recording_id: str) -> dict[str, Any]:
        session_dir, _ = self._load(recording_id)
        summary_path = session_dir / VISUAL_SUMMARY_FILE
        observations_path = session_dir / VISUAL_OBSERVATIONS_FILE
        if not summary_path.exists():
            raise FileNotFoundError("Visual intelligence not found")
        observations = []
        if observations_path.exists():
            observations = [json.loads(line) for line in observations_path.read_text(encoding="utf-8").splitlines()]
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        result = {"summary": summary, "observations": observations}
        document_path = session_dir / VISUAL_DOCUMENT_FILE
        if document_path.exists():
            doc = json.loads(document_path.read_text(encoding="utf-8"))
            if not doc.get("observations"):
                doc["observations"] = observations
            result["document"] = doc
        routing_path = session_dir / VISUAL_ROUTING_FILE
        if routing_path.exists():
            result["routing"] = json.loads(routing_path.read_text(encoding="utf-8"))
        self._validate_visual_generation(result)
        return result

    @staticmethod
    def _validate_visual_generation(result: dict[str, Any]) -> None:
        generation_id = result["summary"].get("generation_id")
        if not generation_id:
            return
        for key in ("document", "routing"):
            artifact = result.get(key)
            if artifact is not None and artifact.get("generation_id") != generation_id:
                raise FileNotFoundError("Visual intelligence generation is incomplete")

    def _visual_source_validity(
        self,
        recording_id: str,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        """Project whether a persisted visual result still matches current screenshot evidence.

        Visual artifacts are immutable history. This projection lets consumers distinguish
        a historical result from one whose manual screenshot sources are still current.
        """
        sources = [
            item
            for item in document.get("manual_screenshot_sources") or []
            if isinstance(item, dict) and item.get("screenshot_id")
        ]
        if not sources:
            return {
                "status": "current",
                "manual_screenshot_count": 0,
                "missing_screenshot_ids": [],
                "unavailable_screenshot_ids": [],
                "changed_screenshot_ids": [],
            }

        current = {
            str(item.get("screenshot_id")): item
            for item in self.list_screenshots(recording_id)
            if item.get("screenshot_id")
        }
        missing: list[str] = []
        unavailable: list[str] = []
        changed: list[str] = []
        for source in sources:
            screenshot_id = str(source["screenshot_id"])
            item = current.get(screenshot_id)
            source_status = str(source.get("status") or "")
            source_expected_asset = source_status != "asset_missing"
            if item is None:
                if source_expected_asset:
                    missing.append(screenshot_id)
                continue
            if not item.get("available"):
                if source_expected_asset:
                    unavailable.append(screenshot_id)
                continue
            expected_sha = str(source.get("sha256") or "")
            current_sha = str(item.get("sha256") or "")
            if expected_sha and current_sha and expected_sha != current_sha:
                changed.append(screenshot_id)

        return {
            "status": "stale" if (missing or unavailable or changed) else "current",
            "manual_screenshot_count": len(sources),
            "missing_screenshot_ids": missing,
            "unavailable_screenshot_ids": unavailable,
            "changed_screenshot_ids": changed,
        }

    def get_visual_intelligence_v2(self, recording_id: str) -> dict[str, Any]:
        """Read the canonical v2 document without changing the legacy response."""
        session_dir, _ = self._load(recording_id)
        document_path = session_dir / VISUAL_DOCUMENT_FILE
        if not document_path.exists():
            raise FileNotFoundError("Visual intelligence v2 not found")
        document = json.loads(document_path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 2:
            raise ValueError("Unsupported visual intelligence schema")
        if not document.get("observations"):
            observations_path = session_dir / VISUAL_OBSERVATIONS_FILE
            if observations_path.exists():
                try:
                    document["observations"] = [
                        json.loads(line)
                        for line in observations_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                except Exception:
                    document["observations"] = []
            else:
                document["observations"] = []
        summary_path = session_dir / VISUAL_SUMMARY_FILE
        response = {
            "schema_version": 2,
            "summary": json.loads(summary_path.read_text(encoding="utf-8")),
            "document": document,
            "source_validity": self._visual_source_validity(recording_id, document),
        }
        routing_path = session_dir / VISUAL_ROUTING_FILE
        if routing_path.exists():
            response["routing"] = json.loads(routing_path.read_text(encoding="utf-8"))
        self._validate_visual_generation({
            "summary": response["summary"],
            "document": response["document"],
            **({"routing": response["routing"]} if "routing" in response else {}),
        })
        return response

    def get_intelligence(self, recording_id: str) -> dict[str, Any]:
        session_dir, _ = self._load(recording_id)
        intelligence_path = session_dir / "intelligence.json"
        if not intelligence_path.exists():
            raise FileNotFoundError("Audio intelligence not found")
        with intelligence_path.open("r", encoding="utf-8") as intelligence_file:
            return json.load(intelligence_file)

    def finalize(self, recording_id: str) -> tuple[dict[str, Any], bool]:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            metadata = self._ensure_tracks(metadata)
            if metadata["status"] in {"recorded", "transcribing", "completed", "failed"}:
                return self.public_metadata(metadata), False
            if metadata["status"] != "recording":
                raise RecordingConflict(
                    f"Cannot stop recording in status {metadata['status']}"
                )
            # Allow empty recordings – the user may have stopped
            # before the first chunk interval elapsed.

            metadata["status"] = "finalizing"
            metadata["stopped_at"] = _utc_now()
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)

            for track in metadata["audio_tracks"]:
                part_path = self._track_part_path(session_dir, track)
                audio_path = self._track_audio_path(session_dir, track)
                if part_path.exists():
                    part_size = part_path.stat().st_size
                    if part_size > 0 or not audio_path.exists():
                        part_path.replace(audio_path)
                    else:
                        part_path.unlink()
                elif audio_path.exists():
                    pass
                elif not audio_path.exists():
                    # No data was written; create an empty file.
                    audio_path.touch()
                track["audio_file"] = self._relative_track_audio_file(metadata, track)
                try:
                    track["bytes_written"] = audio_path.stat().st_size
                    if track["bytes_written"] > 0 and track.get("chunk_count", 0) == 0:
                        track["chunk_count"] = 1
                except OSError:
                    pass

            metadata["status"] = "recorded"
            metadata["capture_status"] = "stopped"
            self._sync_legacy_totals(metadata)
            self._write_timeline(session_dir, metadata)
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self.public_metadata(metadata), False

    def recover(self, recording_id: str) -> dict[str, Any]:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            metadata = self._ensure_tracks(metadata)
            if metadata["status"] in {"recorded", "transcribing", "completed"}:
                return self.public_metadata(metadata)
            if metadata["status"] not in {"recording", "finalizing", "interrupted", "recoverable", "failed"}:
                raise RecordingConflict(f"Cannot recover recording in status {metadata['status']}")
            if not self._has_recoverable_audio(session_dir, metadata):
                raise RecordingConflict("Recording has no recoverable audio")

            metadata["status"] = "recorded"
            metadata["partial"] = True
            metadata["stopped_at"] = metadata.get("stopped_at") or _utc_now()
            metadata["completed_at"] = None
            metadata["error"] = None
            for track in metadata["audio_tracks"]:
                part_path = self._track_part_path(session_dir, track)
                audio_path = self._track_audio_path(session_dir, track)
                if part_path.exists():
                    part_path.replace(audio_path)
                elif not audio_path.exists():
                    audio_path.touch()
                track["audio_file"] = self._relative_track_audio_file(metadata, track)
            self._sync_legacy_totals(metadata)
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)
            return self.public_metadata(metadata)

    def discard(self, recording_id: str) -> None:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            if metadata["status"] not in {"recording", "finalizing", "interrupted", "recoverable", "failed"}:
                raise RecordingConflict(f"Cannot discard recording in status {metadata['status']}")
            shutil.rmtree(session_dir)
            if self.catalog is not None:
                self.catalog.delete_recording(recording_id)

    def get(self, recording_id: str, include_result: bool = True) -> dict[str, Any]:
        _, metadata = self._load(recording_id)
        response = self.public_metadata(metadata)
        if include_result:
            result_path = self._session_dir(metadata) / "transcript.json"
            if result_path.exists():
                with result_path.open("r", encoding="utf-8") as result_file:
                    response["result"] = json.load(result_file)
        return response

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        items = []
        for metadata_path in self.root.glob("*/*/metadata.json"):
            try:
                with metadata_path.open("r", encoding="utf-8") as metadata_file:
                    items.append(self.public_metadata(json.load(metadata_file)))
            except (OSError, json.JSONDecodeError, KeyError):
                continue
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items[: max(1, min(limit, 100))]

    def active_recording(self) -> dict[str, Any] | None:
        """Return the newest persisted recording that is still being captured."""
        active = [item for item in self.list(limit=100) if item.get("status") == "recording"]
        return active[0] if active else None

    def audio_path(self, recording_id: str) -> Path:
        session_dir, metadata = self._load(recording_id)
        metadata = self._ensure_tracks(metadata)
        audio_path = self._track_audio_path(session_dir, self._primary_track(metadata))
        if not audio_path.exists():
            raise RecordingConflict("Finalized recording file does not exist")
        return audio_path

    def track_audio_path(self, recording_id: str, track_id: str) -> Path:
        session_dir, metadata = self._load(recording_id)
        metadata = self._ensure_tracks(metadata)
        track = self._track_for(metadata, track_id)
        audio_path = self._track_audio_path(session_dir, track)
        if not audio_path.exists():
            raise RecordingConflict("Finalized recording track does not exist")
        return audio_path

    def transcribable_tracks(self, recording_id: str) -> list[tuple[dict[str, Any], Path]]:
        session_dir, metadata = self._load(recording_id)
        metadata = self._ensure_tracks(metadata)
        tracks = [
            track
            for track in metadata["audio_tracks"]
            if track["source"] in {"mic", "system"}
        ]
        if not tracks:
            tracks = [self._primary_track(metadata)]
        result = []
        for track in tracks:
            audio_path = self._track_audio_path(session_dir, track)
            if not audio_path.exists():
                raise RecordingConflict(f"Track {track['id']} does not have finalized audio")
            result.append((track, audio_path))
        return result

    def complete(self, recording_id: str, result: dict[str, Any]) -> None:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            if metadata["status"] != "transcribing":
                raise RecordingConflict(
                    f"Cannot complete recording in status {metadata['status']}"
                )
            self._write_json_atomic(session_dir / "transcript.json", result)
            self._write_text_atomic(session_dir / "transcript.txt", result.get("text", ""))
            metadata["status"] = "completed"
            metadata["completed_at"] = _utc_now()
            metadata["error"] = None
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)

    def save_speaker_diarization(self, recording_id: str, payload: dict[str, Any]) -> None:
        """Persist the post-meeting diarization timeline for audit and reuse."""
        with self._lock_for(recording_id):
            session_dir, _ = self._load(recording_id)
            self._write_json_atomic(session_dir / "speaker-diarization.json", payload)

    def fail(self, recording_id: str, error: str) -> None:
        with self._lock_for(recording_id):
            session_dir, metadata = self._load(recording_id)
            metadata["status"] = "failed"
            metadata["completed_at"] = _utc_now()
            metadata["error"] = error[:2000]
            self._write_metadata(session_dir, metadata)
            self._upsert_catalog(metadata)

    def public_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        metadata = self._ensure_tracks(metadata)
        session_dir = self._session_dir(metadata)
        primary = self._primary_track(metadata)
        audio_path = self._track_audio_path(session_dir, primary)
        public_tracks = []
        for track in metadata["audio_tracks"]:
            track_audio_path = self._track_audio_path(session_dir, track)
            public_tracks.append({
                key: value
                for key, value in track.items()
                if key != "extension"
            } | {
                "audio_file": (
                    self._relative_track_audio_file(metadata, track)
                    if track_audio_path.exists()
                    else None
                )
            })
        public = {
            key: value
            for key, value in metadata.items()
            if key not in {"extension", "relative_dir", "audio_tracks"}
        } | {
            "audio_tracks": public_tracks,
            "audio_file": (
                self._relative_track_audio_file(metadata, primary)
                if audio_path.exists()
                else None
            )
        }
        public["chunk_count"] = primary.get("chunk_count", public.get("chunk_count", 0))
        public["bytes_written"] = sum(track.get("bytes_written", 0) for track in metadata["audio_tracks"])
        public["mime_type"] = primary.get("mime_type") or public.get("mime_type")
        return public

    def _load(self, recording_id: str) -> tuple[Path, dict[str, Any]]:
        try:
            normalized_id = str(uuid.UUID(recording_id))
        except ValueError as exc:
            raise RecordingNotFound(recording_id) from exc

        roots = [self.root]
        if self._default_root not in roots:
            roots.append(self._default_root)
        matches = [
            match
            for root in roots
            for match in root.glob(f"*/{normalized_id}/metadata.json")
        ]
        if len(matches) != 1:
            raise RecordingNotFound(recording_id)
        metadata_path = matches[0]
        with metadata_path.open("r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
        metadata = self._ensure_tracks(metadata)
        return metadata_path.parent, metadata

    def _session_dir(self, metadata: dict[str, Any]) -> Path:
        roots = [self.root]
        if self._default_root not in roots:
            roots.append(self._default_root)
        candidates = []
        for root in roots:
            path = (root / metadata["relative_dir"]).resolve()
            if root not in path.parents:
                raise RecordingConflict("Invalid recording path")
            candidates.append(path)
        return next((path for path in candidates if path.exists()), candidates[0])

    def _part_path(self, session_dir: Path, metadata: dict[str, Any]) -> Path:
        return session_dir / f"recording{metadata['extension']}.part"

    def _audio_path(self, session_dir: Path, metadata: dict[str, Any]) -> Path:
        return session_dir / f"recording{metadata['extension']}"

    def _track_file_stem(self, track_id: str) -> str:
        return "recording" if track_id == "mixed" else track_id

    def _track_part_path(self, session_dir: Path, track: dict[str, Any]) -> Path:
        return session_dir / f"{self._track_file_stem(track['id'])}{track['extension']}.part"

    def _track_audio_path(self, session_dir: Path, track: dict[str, Any]) -> Path:
        return session_dir / f"{self._track_file_stem(track['id'])}{track['extension']}"

    def _relative_track_audio_file(self, metadata: dict[str, Any], track: dict[str, Any]) -> str:
        return f"{metadata['relative_dir']}/{self._track_file_stem(track['id'])}{track['extension']}"

    def _track_ids_for_mode(self, capture_mode: str) -> list[str]:
        if capture_mode == "both":
            return ["mixed", "mic", "system"]
        if capture_mode == "mic_only":
            return ["mic"]
        if capture_mode == "pc_only":
            return ["system"]
        return ["mixed"]

    def _primary_track_id_for_mode(self, capture_mode: str) -> str:
        if capture_mode == "mic_only":
            return "mic"
        if capture_mode == "pc_only":
            return "system"
        return "mixed"

    def _ensure_tracks(self, metadata: dict[str, Any]) -> dict[str, Any]:
        if metadata.get("audio_tracks"):
            for track in metadata["audio_tracks"]:
                self._track_chunks(track)
            return metadata
        track_id = metadata.get("primary_track_id") or "mixed"
        extension = metadata.get("extension") or _extension_for_mime(metadata.get("mime_type", "audio/webm"))
        metadata["capture_mode"] = metadata.get("capture_mode") or "legacy_mixed"
        metadata["primary_track_id"] = track_id
        metadata["audio_tracks"] = [{
            "id": track_id,
            "source": TRACK_SOURCES.get(track_id, "mixed"),
            "label": TRACK_LABELS.get(track_id, "Conversazione"),
            "mime_type": metadata.get("mime_type", "audio/webm"),
            "extension": extension,
            "chunk_count": metadata.get("chunk_count", 0),
            "bytes_written": metadata.get("bytes_written", 0),
            "chunks": [],
            "primary": True,
            "audio_file": None,
        }]
        return metadata

    def _track_for(self, metadata: dict[str, Any], track_id: str) -> dict[str, Any]:
        for track in metadata["audio_tracks"]:
            if track["id"] == track_id:
                return track
        raise RecordingConflict(f"Unknown recording track: {track_id}")

    def _primary_track(self, metadata: dict[str, Any]) -> dict[str, Any]:
        primary_track_id = metadata.get("primary_track_id") or "mixed"
        try:
            return self._track_for(metadata, primary_track_id)
        except RecordingConflict:
            return metadata["audio_tracks"][0]

    def _sync_legacy_totals(self, metadata: dict[str, Any]) -> None:
        primary = self._primary_track(metadata)
        metadata["chunk_count"] = primary.get("chunk_count", 0)
        metadata["bytes_written"] = sum(track.get("bytes_written", 0) for track in metadata.get("audio_tracks", []))
        metadata["mime_type"] = primary.get("mime_type", metadata.get("mime_type"))
        metadata["extension"] = primary.get("extension", metadata.get("extension"))

    def _track_chunks(self, track: dict[str, Any]) -> list[dict[str, Any]]:
        chunks = track.setdefault("chunks", [])
        if not isinstance(chunks, list):
            chunks = []
            track["chunks"] = chunks
        return chunks

    def _lock_for(self, recording_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(recording_id, threading.Lock())

    def _write_metadata(self, session_dir: Path, metadata: dict[str, Any]) -> None:
        if metadata["status"] not in VALID_STATUSES:
            raise RecordingConflict(f"Invalid status: {metadata['status']}")
        self._write_json_atomic(session_dir / "metadata.json", metadata)

    def _write_json_atomic(self, path: Path, data: dict[str, Any]) -> None:
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_text_atomic(self, path: Path, text: str) -> None:
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as output:
                output.write(text)
                output.flush()
                os.fsync(output.fileno())
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_bytes_atomic(self, path: Path, content: bytes) -> None:
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_timeline(self, session_dir: Path, metadata: dict[str, Any]) -> None:
        timeline = metadata.get("timeline")
        if timeline is not None:
            self._write_json_atomic(session_dir / "timeline.json", timeline)


    def _reconcile_screenshot_assets(self) -> None:
        """Reconcile persisted screenshot manifests and assets after an unclean stop.

        The manifest remains canonical. Missing assets are preserved as unavailable
        evidence markers, while unreferenced temporary/orphan files are removed.
        """
        for metadata_path in self.root.glob("*/*/metadata.json"):
            session_dir = metadata_path.parent
            screenshots_dir = self._screenshots_dir(session_dir)
            shutil.rmtree(session_dir / ".screenshot-capture-temp", ignore_errors=True)
            if not screenshots_dir.exists():
                continue
            try:
                with metadata_path.open("r", encoding="utf-8") as metadata_file:
                    metadata = json.load(metadata_file)
                recording_id = str(metadata.get("id") or session_dir.name)
                manifest_path = self._screenshot_manifest_path(session_dir)
                if not manifest_path.exists():
                    for candidate in screenshots_dir.iterdir():
                        if candidate.is_file() and candidate.name.endswith(".tmp"):
                            candidate.unlink(missing_ok=True)
                    continue

                manifest = self._read_screenshot_manifest(session_dir, recording_id)
                referenced: set[str] = {"manifest.json"}
                for item in manifest["items"]:
                    for key in ("original_file", "thumbnail_file"):
                        name = str(item.get(key) or "")
                        if name:
                            referenced.add(name)

                root = screenshots_dir.resolve()
                for candidate in screenshots_dir.iterdir():
                    if not candidate.is_file() or candidate.name in referenced:
                        continue
                    resolved = candidate.resolve()
                    if root not in resolved.parents:
                        continue
                    # Only assets/temp files owned by this feature are eligible for cleanup.
                    if candidate.suffix.lower() in {".jpg", ".jpeg", ".tmp"}:
                        candidate.unlink(missing_ok=True)

                changed = False
                expected_count = len(manifest["items"])
                if int(metadata.get("screenshot_count") or 0) != expected_count:
                    metadata["screenshot_count"] = expected_count
                    changed = True
                if int(metadata.get("screenshot_manifest_version") or 0) != SCREENSHOT_MANIFEST_VERSION:
                    metadata["screenshot_manifest_version"] = SCREENSHOT_MANIFEST_VERSION
                    changed = True
                if changed:
                    metadata["screenshot_revision"] = int(metadata.get("screenshot_revision") or 0) + 1
                    self._write_metadata(session_dir, metadata)
                    self._upsert_catalog(metadata)
            except (OSError, json.JSONDecodeError, KeyError, RecordingConflict, ValueError):
                logger.warning(
                    "Unable to reconcile screenshot assets for %s",
                    session_dir,
                    exc_info=True,
                )

    def _mark_interrupted_jobs(self) -> None:
        for metadata_path in self.root.glob("*/*/metadata.json"):
            try:
                with metadata_path.open("r", encoding="utf-8") as metadata_file:
                    metadata = json.load(metadata_file)
                metadata = self._ensure_tracks(metadata)
                if metadata.get("status") in {"recording", "finalizing"}:
                    if self._has_recoverable_audio(metadata_path.parent, metadata):
                        metadata["status"] = "recoverable"
                        metadata["stopped_at"] = metadata.get("stopped_at") or _utc_now()
                        metadata["error"] = "Server restarted before recording was stopped"
                    else:
                        metadata["status"] = "interrupted"
                        metadata["stopped_at"] = metadata.get("stopped_at") or _utc_now()
                        metadata["completed_at"] = _utc_now()
                        metadata["error"] = "Server restarted before any audio chunk was committed"
                    self._write_metadata(metadata_path.parent, metadata)
                    self._upsert_catalog(metadata)
            except (OSError, json.JSONDecodeError, KeyError):
                continue

    def _has_recoverable_audio(self, session_dir: Path, metadata: dict[str, Any]) -> bool:
        for track in metadata.get("audio_tracks", []):
            if track.get("bytes_written", 0) > 0 or track.get("chunk_count", 0) > 0:
                return True
            for path in (
                self._track_part_path(session_dir, track),
                self._track_audio_path(session_dir, track),
            ):
                try:
                    if path.exists() and path.stat().st_size > 0:
                        return True
                except OSError:
                    continue
        return False

    def sync_catalog(self) -> None:
        if self.catalog is None:
            return
        for metadata_path in self.root.glob("*/*/metadata.json"):
            try:
                with metadata_path.open("r", encoding="utf-8") as metadata_file:
                    self._upsert_catalog(json.load(metadata_file))
            except (OSError, json.JSONDecodeError, KeyError):
                continue

    def _upsert_catalog(self, metadata: dict[str, Any]) -> None:
        if self.catalog is None:
            return
        public = self.public_metadata(metadata)
        self.catalog.upsert_recording(metadata, audio_file=public.get("audio_file"))