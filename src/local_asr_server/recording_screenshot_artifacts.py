from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


SCREENSHOT_MANIFEST_VERSION = 1
MAX_SCREENSHOT_BYTES = 25 * 1024 * 1024
MAX_SCREENSHOT_THUMBNAIL_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOT_PIXELS = 100_000_000
MAX_SCREENSHOTS_PER_RECORDING = 200
MIN_SCREENSHOT_FREE_BYTES = 32 * 1024 * 1024


class ScreenshotArtifactStore:
    """Own screenshot artifact paths, manifests, and safe public projection.

    RecordingStore remains the recording aggregate owner and keeps lifecycle,
    locking, metadata revision, and catalog synchronization. This collaborator
    owns only screenshot filesystem topology and manifest interpretation.
    """

    def __init__(
        self,
        *,
        conflict_error: Callable[[str], Exception],
        not_found_error: Callable[[str], Exception],
    ) -> None:
        self._conflict_error = conflict_error
        self._not_found_error = not_found_error

    @staticmethod
    def staging_paths(session_dir: Path, token: str) -> tuple[Path, Path]:
        staging_dir = session_dir / ".screenshot-capture-temp"
        return (
            staging_dir / f"{token}.jpg",
            staging_dir / f"{token}-thumb.jpg",
        )

    @staticmethod
    def directory(session_dir: Path) -> Path:
        return session_dir / "screenshots"

    def manifest_path(self, session_dir: Path) -> Path:
        return self.directory(session_dir) / "manifest.json"

    def read_manifest(self, session_dir: Path, recording_id: str) -> dict[str, Any]:
        manifest_path = self.manifest_path(session_dir)
        if not manifest_path.exists():
            return {
                "schema_version": SCREENSHOT_MANIFEST_VERSION,
                "recording_id": recording_id,
                "items": [],
            }
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self._conflict_error("Screenshot manifest is unreadable") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise self._conflict_error("Screenshot manifest is invalid")
        version = int(payload.get("schema_version") or SCREENSHOT_MANIFEST_VERSION)
        if version != SCREENSHOT_MANIFEST_VERSION:
            raise self._conflict_error(f"Unsupported screenshot manifest version: {version}")
        return {
            "schema_version": version,
            "recording_id": recording_id,
            "items": [item for item in payload["items"] if isinstance(item, dict)],
        }

    def public(self, session_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
        screenshots_dir = self.directory(session_dir).resolve()
        original = (screenshots_dir / str(item.get("original_file") or "")).resolve()
        thumbnail = (screenshots_dir / str(item.get("thumbnail_file") or "")).resolve()
        original_ok = screenshots_dir in original.parents and original.is_file()
        thumbnail_ok = screenshots_dir in thumbnail.parents and thumbnail.is_file()
        return {
            key: value
            for key, value in item.items()
            if key not in {"original_file", "thumbnail_file"}
        } | {
            "available": original_ok,
            "thumbnail_available": thumbnail_ok,
        }

    def asset_path(
        self,
        session_dir: Path,
        manifest: dict[str, Any],
        screenshot_id: str,
        *,
        thumbnail: bool = False,
    ) -> Path:
        item = next(
            (entry for entry in manifest["items"] if entry.get("screenshot_id") == screenshot_id),
            None,
        )
        if item is None:
            raise self._not_found_error(screenshot_id)
        key = "thumbnail_file" if thumbnail else "original_file"
        screenshots_dir = self.directory(session_dir).resolve()
        path = (screenshots_dir / str(item.get(key) or "")).resolve()
        if screenshots_dir not in path.parents or not path.is_file():
            raise self._not_found_error(screenshot_id)
        return path

    def delete_assets(self, session_dir: Path, item: dict[str, Any]) -> None:
        screenshots_dir = self.directory(session_dir).resolve()
        for key in ("original_file", "thumbnail_file"):
            path = (screenshots_dir / str(item.get(key) or "")).resolve()
            if screenshots_dir in path.parents:
                path.unlink(missing_ok=True)
