#!/usr/bin/env python3
"""Inspect a ClosedRoom SQLite catalog candidate without mutating it.

Run only after quitting ClosedRoom on the source Mac. Deliberately does not
import/construct CatalogStore (its constructor initializes/migrates a DB).
No SQLite writes, cloud access, filenames, IDs, titles or transcript text
are emitted. A passing result does NOT identify the DB as the active catalog.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.parse import quote


class CatalogInspectionBlocked(RuntimeError):
    """Static diagnostic category; never embed local SQLite exceptions."""


def inspect_catalog(path: Path) -> dict[str, object]:
    try:
        before = path.lstat()
    except FileNotFoundError:
        raise CatalogInspectionBlocked("CATALOG_FILE_MISSING") from None
    except OSError:
        raise CatalogInspectionBlocked("CATALOG_FILE_UNREADABLE") from None
    if not stat.S_ISREG(before.st_mode):
        raise CatalogInspectionBlocked("CATALOG_FILE_NOT_REGULAR")
    # Immutable SQLite connections deliberately ignore WAL data. Never use
    # one when there might be uncheckpointed committed transactions.
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists() or Path(str(path) + suffix).is_symlink():
            raise CatalogInspectionBlocked("CATALOG_SIDECAR_PRESENT_CLOSE_APP_FIRST")

    try:
        with path.open("rb") as stream:
            if stream.read(16) != b"SQLite format 3\x00":
                raise CatalogInspectionBlocked("CATALOG_NOT_SQLITE")
    except OSError:
        raise CatalogInspectionBlocked("CATALOG_FILE_UNREADABLE") from None

    # Immutable=1 neither creates SQLite files nor locks/writes the original.
    # Its consistency requires an idle database with no WAL/journal sidecars.
    uri = "file:" + quote(str(path.absolute()), safe="/") + "?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as db:
            db.execute("PRAGMA query_only=ON")
            integrity = db.execute("PRAGMA quick_check(1)").fetchone()
            if not integrity or integrity[0] != "ok":
                raise CatalogInspectionBlocked("CATALOG_QUICK_CHECK_FAILED")
            tables = {str(row[0]) for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            required = {"recordings", "transcriptions"}
            if not required.issubset(tables):
                raise CatalogInspectionBlocked("CATALOG_SCHEMA_MISSING_REQUIRED_TABLES")
            columns = {
                name: {str(row[1]) for row in db.execute(
                    "PRAGMA table_info(" + name + ")"
                )}
                for name in ("recordings", "transcriptions")
            }
            if "id" not in columns["recordings"] or not (
                {"id", "recording_id"} <= columns["transcriptions"]
            ):
                raise CatalogInspectionBlocked("CATALOG_SCHEMA_MISSING_REQUIRED_COLUMNS")
            recordings = db.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
            transcriptions = db.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
            linked_transcripts = db.execute(
                "SELECT COUNT(*) FROM transcriptions "
                "WHERE recording_id IS NOT NULL AND recording_id <> ''"
            ).fetchone()[0]
            missing_recordings = db.execute(
                "SELECT COUNT(*) FROM transcriptions t "
                "WHERE t.recording_id IS NOT NULL AND t.recording_id <> '' "
                "AND NOT EXISTS (SELECT 1 FROM recordings r WHERE r.id = t.recording_id)"
            ).fetchone()[0]
            analysis_runs = db.execute(
                "SELECT COUNT(*) FROM analysis_runs"
            ).fetchone()[0] if "analysis_runs" in tables else None
    except CatalogInspectionBlocked:
        raise
    except (OSError, sqlite3.Error):
        raise CatalogInspectionBlocked("CATALOG_SQLITE_READ_FAILED") from None

    try:
        after = path.lstat()
    except OSError:
        raise CatalogInspectionBlocked("CATALOG_CHANGED_DURING_INSPECTION") from None
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise CatalogInspectionBlocked("CATALOG_CHANGED_DURING_INSPECTION")
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise CatalogInspectionBlocked("CATALOG_CHANGED_DURING_INSPECTION")

    return {
        "status": "catalog_candidate_read_only_inspected",
        "source": "explicit_local_candidate",
        "quick_check_pass": True,
        "sqlite_required_tables_present": True,
        "recordings_rows": int(recordings),
        "transcriptions_rows": int(transcriptions),
        "transcriptions_with_recording_id": int(linked_transcripts),
        "transcriptions_reference_missing_recording": int(missing_recordings),
        "transcriptions_without_recording_id": int(transcriptions - linked_transcripts),
        "analysis_runs_rows": None if analysis_runs is None else int(analysis_runs),
        "active_catalog_verified": False,
        "full_meeting_restore_verified": False,
        "cloud_transfer_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path,
        default=Path.home() / "Library" / "Application Support" / "ClosedRoom" / "closedroom.db",
        help="Local catalog candidate (default Application Support)",
    )
    args = parser.parse_args(argv)
    try:
        report = inspect_catalog(args.catalog.expanduser())
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except CatalogInspectionBlocked as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)},
                         sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
