#!/usr/bin/env python3
"""Read-only reconciliation of ClosedRoom catalog with on-disk meeting exports.

Requires ClosedRoom to be completely quit. No SQLite initialization, writes,
cloud calls, raw IDs, paths, titles, texts or user-controlled exception output.
A clean result is only a candidate inventory, NOT proof of active catalog,
backup correctness or permission to delete originals.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.parse import quote

DEFAULT_SETTINGS = Path.home() / "Library/Application Support/ClosedRoom/settings.json"
DEFAULT_CATALOG = Path.home() / "Library/Application Support/ClosedRoom/closedroom.db"
DEFAULT_RECORDINGS = Path.home() / "ClosedRoom/Recordings/ClosedRoom"
DEFAULT_TRANSCRIPTS = Path.home() / "ClosedRoom/Transcriptions/ClosedRoom"
MAX_JSON_BYTES = 64 * 1024 * 1024
SIDECARS = ("-wal", "-shm", "-journal")


class ReconciliationBlocked(RuntimeError):
    """A static non-sensitive diagnostic code."""


def _regular_file(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise ReconciliationBlocked("REQUIRED_SOURCE_MISSING") from None
    except OSError:
        raise ReconciliationBlocked("SOURCE_UNREADABLE") from None
    if not stat.S_ISREG(info.st_mode):
        raise ReconciliationBlocked("SOURCE_NOT_REGULAR_FILE")
    return info


def _roots(settings_file: Path) -> tuple[Path, Path]:
    data = {}
    if settings_file.exists() or settings_file.is_symlink():
        info = _regular_file(settings_file)
        if info.st_size > 1024 * 1024:
            raise ReconciliationBlocked("SETTINGS_TOO_LARGE")
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise ReconciliationBlocked("SETTINGS_INVALID") from None
        if not isinstance(data, dict):
            raise ReconciliationBlocked("SETTINGS_INVALID")
    def setting(name: str, default: Path) -> Path:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            return default
        return Path(value).expanduser()
    return setting("recordings_dir", DEFAULT_RECORDINGS), setting(
        "transcriptions_dir", DEFAULT_TRANSCRIPTS
    )


def _directory(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise ReconciliationBlocked("REQUIRED_ROOT_MISSING") from None
    except OSError:
        raise ReconciliationBlocked("ROOT_UNREADABLE") from None
    if not stat.S_ISDIR(mode):
        raise ReconciliationBlocked("ROOT_NOT_REGULAR_DIRECTORY")


def _sidecars_present(path: Path) -> bool:
    return any(Path(str(path) + suffix).exists() or Path(
        str(path) + suffix).is_symlink() for suffix in SIDECARS)


def _source_json(path: Path) -> dict | None:
    """Parse only for in-memory ID comparison, without returning payload."""
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not (0 < info.st_size <= MAX_JSON_BYTES):
            return None
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        after = path.lstat()
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            return None
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, ValueError, TypeError):
        return None


def _scan_exports(root: Path, pattern: str, *, metadata: bool) -> tuple[
    dict[str, str], dict[str, int]
]:
    found: dict[str, str] = {}
    summary = {
        "files": 0,
        "invalid_or_unreadable": 0,
        "duplicate_ids": 0,
        "invalid_identity_or_location": 0,
    }
    for path in root.glob(pattern):
        summary["files"] += 1
        payload = _source_json(path)
        if payload is None:
            summary["invalid_or_unreadable"] += 1
            continue
        uid = payload.get("id")
        if not isinstance(uid, str) or not uid or len(uid) > 128:
            summary["invalid_identity_or_location"] += 1
            continue
        if metadata:
            # RecordingStore owns YYYY-MM-DD/UUID/metadata.json and its
            # relative_dir. Compare without printing any identifier.
            relative = path.parent.relative_to(root).as_posix()
            if payload.get("relative_dir") != relative or path.parent.name != uid:
                summary["invalid_identity_or_location"] += 1
                continue
        if uid in found:
            summary["duplicate_ids"] += 1
        else:
            found[uid] = path.name if not metadata else path.parent.relative_to(root).as_posix()
    return found, summary


def reconcile(
    catalog: Path, recordings_root: Path, transcriptions_root: Path,
) -> dict[str, object]:
    _directory(recordings_root)
    _directory(transcriptions_root)
    before = _regular_file(catalog)
    if _sidecars_present(catalog):
        raise ReconciliationBlocked("CATALOG_SIDECAR_PRESENT_CLOSE_APP_FIRST")
    if before.st_size < 100:
        raise ReconciliationBlocked("CATALOG_NOT_SQLITE")
    try:
        with catalog.open("rb") as stream:
            if stream.read(16) != b"SQLite format 3\x00":
                raise ReconciliationBlocked("CATALOG_NOT_SQLITE")
    except OSError:
        raise ReconciliationBlocked("CATALOG_UNREADABLE") from None

    uri = "file:" + quote(str(catalog.absolute()), safe="/") + "?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
            conn.execute("PRAGMA query_only=ON")
            check = conn.execute("PRAGMA quick_check(1)").fetchone()
            if not check or check[0] != "ok":
                raise ReconciliationBlocked("CATALOG_QUICK_CHECK_FAILED")
            cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(transcriptions)")}
            if not {"id", "file_name", "recording_id"} <= cols:
                raise ReconciliationBlocked("CATALOG_SCHEMA_INCOMPATIBLE")
            recording_ids = {row[0] for row in conn.execute("SELECT id FROM recordings")}
            transcript_rows = conn.execute("SELECT id, file_name FROM transcriptions").fetchall()
            transcript_names = {row[0]: row[1] for row in transcript_rows}
    except ReconciliationBlocked:
        raise
    except (sqlite3.Error, OSError):
        raise ReconciliationBlocked("CATALOG_SQLITE_READ_FAILED") from None

    metadata_ids, metadata = _scan_exports(
        recordings_root, "*/*/metadata.json", metadata=True
    )
    transcript_ids, exports = _scan_exports(
        transcriptions_root, "transcript_*.json", metadata=False
    )
    missing_metadata = recording_ids - metadata_ids.keys()
    extra_metadata = metadata_ids.keys() - recording_ids
    missing_exports = transcript_names.keys() - transcript_ids.keys()
    extra_exports = transcript_ids.keys() - transcript_names.keys()
    mismatched_filenames = sum(
        1 for tid in transcript_ids.keys() & transcript_names.keys()
        if transcript_names[tid] != transcript_ids[tid]
    )
    try:
        after = catalog.lstat()
    except OSError:
        raise ReconciliationBlocked("CATALOG_CHANGED_DURING_READ") from None
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or _sidecars_present(catalog):
        raise ReconciliationBlocked("CATALOG_CHANGED_DURING_READ")

    discrepancies = (
        len(missing_metadata) + len(extra_metadata)
        + len(missing_exports) + len(extra_exports) + mismatched_filenames
        + metadata["invalid_or_unreadable"] + metadata["duplicate_ids"]
        + metadata["invalid_identity_or_location"]
        + exports["invalid_or_unreadable"] + exports["duplicate_ids"]
        + exports["invalid_identity_or_location"]
    )
    return {
        "status": "reconciliation_clean" if discrepancies == 0 else "reconciliation_requires_review",
        "catalog_quick_check_pass": True,
        "recordings_catalog_rows": len(recording_ids),
        "recording_metadata": metadata,
        "recordings_in_catalog_without_metadata": len(missing_metadata),
        "recording_metadata_missing_from_catalog": len(extra_metadata),
        "transcriptions_catalog_rows": len(transcript_names),
        "transcription_json_exports": exports,
        "transcriptions_in_catalog_without_json_export": len(missing_exports),
        "transcription_json_exports_missing_from_catalog": len(extra_exports),
        "transcription_export_file_name_mismatches": mismatched_filenames,
        "active_catalog_verified": False,
        "safe_to_upload_real_meetings": False,
        "cloud_transfer_performed": False,
        "original_files_modified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings-file", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args(argv)
    try:
        rec, trans = _roots(args.settings_file.expanduser())
        report = reconcile(args.catalog.expanduser(), rec, trans)
    except ReconciliationBlocked as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
