"""Non-mutating catalog inspection with aggregate counts only."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.inspect_closedroom_catalog import (
    CatalogInspectionBlocked, inspect_catalog, main,
)


def populate(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE recordings (id TEXT PRIMARY KEY, title TEXT)")
        db.execute("CREATE TABLE transcriptions (id TEXT PRIMARY KEY, recording_id TEXT, text TEXT)")
        db.execute("CREATE TABLE analysis_runs (id TEXT PRIMARY KEY, result_markdown TEXT)")
        db.execute("INSERT INTO recordings VALUES (?, ?)", ("secret-recording-id", "PRIVATE MEETING"))
        db.executemany("INSERT INTO transcriptions VALUES (?, ?, ?)", [
            ("tr1", "secret-recording-id", "PRIVATE TRANSCRIPT"),
            ("tr2", "", "PRIVATE STANDALONE"),
            ("tr3", "missing-recording-id", "PRIVATE ORPHAN"),
        ])
        db.execute("INSERT INTO analysis_runs VALUES (?, ?)", ("run1", "PRIVATE ANALYSIS"))


class CatalogInspectionTests(unittest.TestCase):
    def test_aggregate_counts_and_no_private_data_or_side_effects(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "private-database-name.db"
            populate(db_path)
            before = db_path.stat()
            result = inspect_catalog(db_path)
            self.assertEqual(result["status"], "catalog_candidate_read_only_inspected")
            self.assertEqual(result["recordings_rows"], 1)
            self.assertEqual(result["transcriptions_rows"], 3)
            self.assertEqual(result["transcriptions_with_recording_id"], 2)
            self.assertEqual(result["transcriptions_reference_missing_recording"], 1)
            self.assertEqual(result["transcriptions_without_recording_id"], 1)
            self.assertEqual(result["analysis_runs_rows"], 1)
            self.assertFalse(result["active_catalog_verified"])
            self.assertFalse(result["cloud_transfer_performed"])
            self.assertEqual(db_path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertFalse(Path(str(db_path) + "-wal").exists())
            self.assertFalse(Path(str(db_path) + "-shm").exists())
            emitted = json.dumps(result)
            for private in ["PRIVATE", "secret-recording-id", "missing-recording-id",
                            "private-database-name", str(db_path)]:
                self.assertNotIn(private, emitted)

    def test_missing_or_not_sqlite_fail_without_creating_database(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "missing.db"
            with self.assertRaises(CatalogInspectionBlocked) as err:
                inspect_catalog(p)
            self.assertEqual(str(err.exception), "CATALOG_FILE_MISSING")
            self.assertFalse(p.exists())
            p.write_bytes(b"NOT A DATABASE")
            with self.assertRaises(CatalogInspectionBlocked) as err:
                inspect_catalog(p)
            self.assertEqual(str(err.exception), "CATALOG_NOT_SQLITE")

    def test_wal_sidecar_refuses_even_when_sqlite_db_valid(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "closedroom.db"
            populate(p)
            wal = Path(str(p) + "-wal")
            wal.write_bytes(b"DO NOT IGNORE WAL")
            with self.assertRaises(CatalogInspectionBlocked) as err:
                inspect_catalog(p)
            self.assertEqual(str(err.exception), "CATALOG_SIDECAR_PRESENT_CLOSE_APP_FIRST")
            self.assertEqual(wal.read_bytes(), b"DO NOT IGNORE WAL")

    def test_symlink_refused_without_following(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "target.db"
            populate(p)
            alias = Path(d) / "alias.db"
            alias.symlink_to(p)
            with self.assertRaises(CatalogInspectionBlocked) as err:
                inspect_catalog(alias)
            self.assertEqual(str(err.exception), "CATALOG_FILE_NOT_REGULAR")

    def test_schema_incomplete_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.db"
            with sqlite3.connect(p) as db:
                db.execute("CREATE TABLE recordings (id TEXT PRIMARY KEY)")
            with self.assertRaises(CatalogInspectionBlocked) as err:
                inspect_catalog(p)
            self.assertEqual(str(err.exception), "CATALOG_SCHEMA_MISSING_REQUIRED_TABLES")

    def test_cli_failure_reports_code_not_path(self):
        with tempfile.TemporaryDirectory() as d:
            secret_path = Path(d) / "secret-private-name.db"
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(main(["--catalog", str(secret_path)]), 2)
            report = json.loads(err.getvalue())
            self.assertEqual(report["error_code"], "CATALOG_FILE_MISSING")
            self.assertNotIn("secret-private-name", err.getvalue())


if __name__ == "__main__":
    unittest.main()
