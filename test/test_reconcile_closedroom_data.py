"""Read-only, privacy-preserving reconciliation of ClosedRoom fixture data."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.reconcile_closedroom_data import (
    ReconciliationBlocked, main, reconcile,
)


def fixture(root: Path):
    rec = root / "recordings"
    trans = root / "transcriptions"
    rec.mkdir()
    trans.mkdir()
    catalog = root / "closedroom.db"
    with sqlite3.connect(catalog) as conn:
        conn.execute("CREATE TABLE recordings (id TEXT PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE transcriptions (id TEXT PRIMARY KEY, "
            "recording_id TEXT, file_name TEXT)"
        )
        conn.execute("INSERT INTO recordings VALUES ('12345678-aaaa-4444-8888-111111111111')")
        conn.execute("INSERT INTO transcriptions VALUES "
                     "('transcript-secret-id', '12345678-aaaa-4444-8888-111111111111', "
                     "'transcript_20261030_secret.json')")
    folder = rec / "2026-10-30" / "12345678-aaaa-4444-8888-111111111111"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(json.dumps({
        "id": folder.name, "relative_dir": folder.relative_to(rec).as_posix(),
        "title": "PRIVATE MEETING", "notes": "SECRET NOTES",
    }))
    (trans / "transcript_20261030_secret.json").write_text(json.dumps({
        "id": "transcript-secret-id", "text": "PRIVATE TRANSCRIPTION",
    }))
    (trans / "transcript_20261030_secret.txt").write_text("PRIVATE TRANSCRIPTION")
    return catalog, rec, trans


class ReconciliationTests(unittest.TestCase):
    def test_clean_fixture_counts_one_json_not_txt_and_does_not_modify(self):
        with tempfile.TemporaryDirectory() as d:
            cat, rec, trans = fixture(Path(d))
            catalog_stat = cat.stat().st_mtime_ns
            metadata_path = next(rec.glob("*/*/metadata.json"))
            meta_stat = metadata_path.stat().st_mtime_ns
            result = reconcile(cat, rec, trans)
            self.assertEqual(result["status"], "reconciliation_clean")
            self.assertEqual(result["recordings_catalog_rows"], 1)
            self.assertEqual(result["recording_metadata"]["files"], 1)
            self.assertEqual(result["transcription_json_exports"]["files"], 1)
            self.assertEqual(result["transcriptions_catalog_rows"], 1)
            self.assertFalse(result["safe_to_upload_real_meetings"])
            self.assertFalse(result["active_catalog_verified"])
            self.assertFalse(result["cloud_transfer_performed"])
            self.assertEqual(cat.stat().st_mtime_ns, catalog_stat)
            self.assertEqual(metadata_path.stat().st_mtime_ns, meta_stat)
            for confidential in ["PRIVATE", "12345678-aaaa", "secret-id", "SECRET NOTES", str(rec)]:
                self.assertNotIn(confidential, json.dumps(result))
            self.assertFalse(Path(str(cat) + "-wal").exists())

    def test_additional_recording_metadata_and_missing_transcript_mark_review(self):
        with tempfile.TemporaryDirectory() as d:
            cat, rec, trans = fixture(Path(d))
            extra = rec / "2026-10-30" / "22222222-aaaa-4444-8888-111111111111"
            extra.mkdir()
            (extra / "metadata.json").write_text(json.dumps({
                "id": extra.name, "relative_dir": extra.relative_to(rec).as_posix(),
                "title": "ANOTHER PRIVATE MEETING",
            }))
            (trans / "transcript_20261030_secret.json").unlink()
            report = reconcile(cat, rec, trans)
            self.assertEqual(report["status"], "reconciliation_requires_review")
            self.assertEqual(report["recording_metadata_missing_from_catalog"], 1)
            self.assertEqual(report["transcriptions_in_catalog_without_json_export"], 1)

    def test_missing_catalog_rows_and_mismatched_export_name(self):
        with tempfile.TemporaryDirectory() as d:
            cat, rec, trans = fixture(Path(d))
            with sqlite3.connect(cat) as db:
                db.execute("INSERT INTO recordings VALUES ('missing-recording-id')")
                db.execute("UPDATE transcriptions SET file_name='other-export.json'")
            report = reconcile(cat, rec, trans)
            self.assertEqual(report["recordings_in_catalog_without_metadata"], 1)
            self.assertEqual(report["transcription_export_file_name_mismatches"], 1)

    def test_wal_does_not_get_ignored_or_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            cat, rec, trans = fixture(Path(d))
            wal = Path(str(cat) + "-wal")
            wal.write_bytes(b"DO NOT READ STALE SQLITE")
            with self.assertRaises(ReconciliationBlocked) as caught:
                reconcile(cat, rec, trans)
            self.assertEqual(str(caught.exception), "CATALOG_SIDECAR_PRESENT_CLOSE_APP_FIRST")
            self.assertTrue(wal.exists())

    def test_invalid_metadata_and_symlink_never_read_secret(self):
        with tempfile.TemporaryDirectory() as d:
            cat, rec, trans = fixture(Path(d))
            metadata = next(rec.glob("*/*/metadata.json"))
            target = Path(d) / "private-external.json"
            target.write_text(json.dumps({"id": "sensitive-id", "title": "PRIVATE"}))
            metadata.unlink()
            metadata.symlink_to(target)
            report = reconcile(cat, rec, trans)
            self.assertEqual(report["recording_metadata"]["invalid_or_unreadable"], 1)
            self.assertEqual(report["recordings_in_catalog_without_metadata"], 1)
            self.assertNotIn("sensitive-id", json.dumps(report))

    def test_cli_uses_private_settings_without_emitting_paths(self):
        with tempfile.TemporaryDirectory() as d:
            cat, rec, trans = fixture(Path(d))
            settings = Path(d) / "secret-settings.json"
            settings.write_text(json.dumps({
                "recordings_dir": str(rec), "transcriptions_dir": str(trans),
                "gemini_api_key": "secret-token",
            }))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main([
                    "--catalog", str(cat), "--settings-file", str(settings)
                ]), 0)
            report = json.loads(out.getvalue())
            self.assertEqual(report["status"], "reconciliation_clean")
            self.assertNotIn(str(cat), out.getvalue())
            self.assertNotIn("secret-token", out.getvalue())
            self.assertNotIn("PRIVATE", out.getvalue())


if __name__ == "__main__":
    unittest.main()
