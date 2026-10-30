"""One-shot migration: encrypted archive, catalog snapshot, restored app paths.

Entirely synthetic. Fake GCS and Keychain; no credentials, data or network.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import sqlite3
import tempfile
import tarfile
import unittest

from local_asr_server.storage.gcs_archive import GCSArchiveTransport, ArchiveIntegrityError
from local_asr_server.storage.key_recovery import ArchiveKeyVault
from local_asr_server.storage.cold_migration import (
    MigrationBlocked, upload_snapshot, restore_snapshot, activate_import,
    prepare_snapshot,
)
from scripts.migrate_closedroom_gcs import main
from scripts.probe_closedroom_gcs_oauth import TEST_BUCKET


class KeychainFake:
    def __init__(self):
        self.items = {}
    def get_password(self, service, name):
        return self.items.get((service, name))
    def set_password(self, service, name, value):
        self.items[(service, name)] = value
    def delete_password(self, service, name):
        self.items.pop((service, name), None)


class BucketFake:
    name = TEST_BUCKET
    def __init__(self):
        self.objects = {}
        self.calls = []
    def blob(self, name, generation=None):
        parent = self
        class Blob:
            def __init__(self):
                self.generation = generation
            def upload_from_filename(self, filename, **kwargs):
                assert kwargs["if_generation_match"] == 0
                assert kwargs["checksum"] == "auto"
                assert name not in parent.objects
                parent.objects[name] = Path(filename).read_bytes()
                parent.calls.append("upload")
                self.generation = 731
            def download_to_filename(self, filename, **kwargs):
                assert generation == kwargs["if_generation_match"] == 731
                Path(filename).write_bytes(parent.objects[name])
                parent.calls.append("download")
        return Blob()


def source_data(root: Path):
    rec = root / "recordings"
    trans = root / "transcriptions"
    rec.mkdir()
    trans.mkdir()
    folder = rec / "2026-10-30" / "recording-abc"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(json.dumps({
        "id": "recording-abc",
        "title": "SECRET_PRIVATE_MEETING",
        "relative_dir": "2026-10-30/recording-abc",
    }))
    (folder / "mic.wav").write_bytes(b"SECRET_REAL_AUDIO_FAKE_" * 150)
    (folder / "mic.wav.part").write_bytes(b"")
    (trans / "transcript_example.json").write_text(json.dumps({
        "id": "trans-id",
        "recording_id": "recording-abc",
        "text": "PRIVATE_FULL_TRANSCRIPT",
    }))
    (trans / "transcript_example.txt").write_text("PRIVATE_FULL_TRANSCRIPT")
    catalog = root / "original.db"
    with sqlite3.connect(catalog) as db:
        db.execute("CREATE TABLE recordings (id TEXT PRIMARY KEY, title TEXT)")
        db.execute("CREATE TABLE transcriptions (id TEXT PRIMARY KEY, recording_id TEXT, text TEXT)")
        db.execute("INSERT INTO recordings VALUES (?, ?)", ("recording-abc", "SECRET_PRIVATE_MEETING"))
        # Intentionally record without a physical metadata file: migration
        # must preserve it rather than refuse all exports.
        db.execute("INSERT INTO recordings VALUES (?, ?)", ("legacy-db-only", "OLD_ARCHIVE"))
        db.execute("INSERT INTO transcriptions VALUES (?, ?, ?)",
                   ("trans-id", "recording-abc", "PRIVATE_FULL_TRANSCRIPT"))
        db.execute("INSERT INTO transcriptions VALUES (?, ?, ?)",
                   ("legacy-transcript-no-file", "", "KEEP_DB_ONLY"))
    settings = root / "settings.json"
    settings.write_text(json.dumps({
        "recordings_dir": str(rec), "transcriptions_dir": str(trans),
        "catalog_db_path": str(root / "missing-configured.db"),
        "llm_provider": "mock",
    }))
    return rec, trans, catalog, settings


class ColdMigrationCLITests(unittest.TestCase):
    def test_operator_script_imports_with_exact_user_pythonpath(self):
        # Reproduce: uv run --no-project sets PYTHONPATH=src and executes a
        # file from scripts/, where the project root is NOT on sys.path.
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = "src"
        env.pop("PYTHONSAFEPATH", None)
        for cli in ("scripts/migrate_closedroom_gcs.py", "scripts/probe_closedroom_gcs_oauth.py"):
            with self.subTest(cli=cli):
                run = subprocess.run(
                    [sys.executable, "-P", cli, "--help"],
                    cwd=root, env=env, capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn("usage:", run.stdout.lower())

    def test_backup_cli_refuses_without_upload_consent(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = "src"
        result = subprocess.run(
            [sys.executable, "-P", "scripts/migrate_closedroom_gcs.py", "backup", "--apply"],
            cwd=root, env=env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            json.loads(result.stderr)["error_code"], "REAL_MEETING_UPLOAD_CONSENT_REQUIRED"
        )


class ColdMigrationTests(unittest.TestCase):
    def test_complete_encrypted_snapshot_and_isolated_restore_preserves_db_only_rows(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec, trans, catalog, settings = source_data(root)
            work = root / "work"
            work.mkdir(mode=0o700)
            receipt = root / "receipt.json"
            envelope = root / "recovery.json"
            bucket = BucketFake()
            transport = GCSArchiveTransport(bucket, bucket_name=TEST_BUCKET)
            mac_a = ArchiveKeyVault(backend=KeychainFake())
            report, code = upload_snapshot(
                client_json=root / "no-client-needed-with-fake.json",
                settings_file=settings, catalog=catalog, work_dir=work,
                receipt=receipt, recovery_file=envelope, transport=transport, vault=mac_a,
            )
            self.assertEqual(report["status"], "cold_snapshot_uploaded_pending_restore")
            self.assertTrue((rec / "2026-10-30/recording-abc/mic.wav").exists())
            self.assertEqual(len(bucket.objects), 1)
            ciphertext = next(iter(bucket.objects.values()))
            self.assertNotIn(b"SECRET_REAL_AUDIO_FAKE_", ciphertext)
            self.assertNotIn(b"PRIVATE_FULL_TRANSCRIPT", ciphertext)
            self.assertEqual(envelope.stat().st_mode & 0o077, 0)
            self.assertEqual(receipt.stat().st_mode & 0o077, 0)
            self.assertTrue(code.startswith("CR1-"))

            dest = root / "restored-app-data"
            mac_b = ArchiveKeyVault(backend=KeychainFake())
            restored = restore_snapshot(
                client_json=root / "not-needed.json", receipt=receipt,
                recovery_file=envelope, recovery_code=code,
                target=dest, work_dir=work, transport=transport, vault=mac_b,
            )
            self.assertEqual(restored["status"], "cold_snapshot_restored_to_isolated_directory")
            self.assertFalse(restored["activated_in_app"])
            self.assertEqual(
                (dest / "recordings/2026-10-30/recording-abc/mic.wav").read_bytes(),
                (rec / "2026-10-30/recording-abc/mic.wav").read_bytes(),
            )
            self.assertEqual(
                (dest / "transcriptions/transcript_example.json").read_bytes(),
                (trans / "transcript_example.json").read_bytes(),
            )
            with sqlite3.connect(dest / "catalog/closedroom.db") as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0], 2)
                self.assertEqual(
                    db.execute("SELECT title FROM recordings WHERE id='legacy-db-only'").fetchone()[0],
                    "OLD_ARCHIVE",
                )
            self.assertEqual(bucket.calls, ["upload", "download"])
            with self.assertRaises(MigrationBlocked):
                restore_snapshot(client_json=root / "not-needed.json", receipt=receipt,
                                 recovery_file=envelope, recovery_code=code, target=dest,
                                 transport=transport, vault=mac_b)
            # Activation changes only the user's local pointer, never
            # uploads/deletes/mixes existing data or enables cloud runtime.
            app_settings = root / "app-support" / "settings.json"
            app_settings.parent.mkdir()
            app_settings.write_text(json.dumps({
                "recordings_dir": "/existing/user/data",
                "gemini_api_key": "DO_NOT_LEAK_TO_GCS",
                "storage_mode": "local",
            }))
            activated = activate_import(dest, app_settings)
            self.assertEqual(activated["status"], "isolated_import_activated_local_only")
            self.assertFalse(activated["gcs_runtime_enabled"])
            active = json.loads(app_settings.read_text())
            self.assertEqual(active["catalog_db_path"], str(dest / "catalog/closedroom.db"))
            self.assertEqual(active["recordings_dir"], str(dest / "recordings"))
            self.assertEqual(active["gemini_api_key"], "DO_NOT_LEAK_TO_GCS")
            backups = list(app_settings.parent.glob("settings.pre-migration-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text())["recordings_dir"],
                             "/existing/user/data")
            self.assertEqual(len(bucket.objects), 1)

    def test_idle_wal_source_does_not_create_sidecars_during_cold_backup(self):
        """Regression: SQLite mode=ro creates WAL/SHM for an idle WAL DB.

        The earlier operator backup failed with CATALOG_CHANGED_DURING_SNAPSHOT.
        Use the real WAL journal mode with last writer closed, then ensure
        the SQLite source remains untouched and the archived DB is complete.
        """
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec, trans, catalog, settings = source_data(root)
            with sqlite3.connect(catalog) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                db.execute("INSERT INTO recordings VALUES (?, ?)", (
                    "wal-committed-row", "VERY_PRIVATE_ADDITIONAL_MEETING",
                ))
                db.commit()
            self.assertFalse(Path(str(catalog) + "-wal").exists())
            self.assertFalse(Path(str(catalog) + "-shm").exists())
            before = catalog.stat()
            work = root / "work"
            work.mkdir()
            archive = work / "snapshot.tar"
            report = prepare_snapshot(rec, trans, catalog, archive, work)
            self.assertGreaterEqual(report["file_count"], 5)
            self.assertTrue(archive.exists())
            after = catalog.stat()
            self.assertEqual(
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            )
            self.assertFalse(Path(str(catalog) + "-wal").exists())
            self.assertFalse(Path(str(catalog) + "-shm").exists())
            self.assertFalse(Path(str(catalog) + "-journal").exists())
            with tempfile.TemporaryDirectory() as restored:
                with tarfile.open(archive) as tar:
                    extracted_db = tar.extractfile("catalog/closedroom.db")
                    self.assertIsNotNone(extracted_db)
                    (Path(restored) / "copy.db").write_bytes(extracted_db.read())
                with sqlite3.connect(Path(restored) / "copy.db") as check:
                    self.assertEqual(
                        check.execute("PRAGMA quick_check(1)").fetchone(), ("ok",),
                    )
                    self.assertEqual(
                        check.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 3,
                    )
                    self.assertEqual(
                        check.execute("SELECT title FROM recordings "
                                      "WHERE id='wal-committed-row'").fetchone()[0],
                        "VERY_PRIVATE_ADDITIONAL_MEETING",
                    )

    def test_live_sqlite_sidecar_is_never_ignored_or_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec, trans, catalog, settings = source_data(root)
            work = root / "work"
            work.mkdir()
            wal = Path(str(catalog) + "-wal")
            wal.write_bytes(b"UNCOMMITTED")
            with self.assertRaises(MigrationBlocked) as caught:
                upload_snapshot(client_json=root / "unused", settings_file=settings,
                                catalog=catalog, work_dir=work, receipt=root / "receipt",
                                recovery_file=root / "recovery", transport=GCSArchiveTransport(
                                BucketFake(), bucket_name=TEST_BUCKET),
                                vault=ArchiveKeyVault(backend=KeychainFake()))
            self.assertEqual(str(caught.exception), "CATALOG_HAS_LIVE_SIDECAR_CLOSE_APP")
            self.assertTrue(wal.exists())
            self.assertFalse((root / "receipt").exists())

    def test_symlink_source_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec, trans, catalog, settings = source_data(root)
            work = root / "work"; work.mkdir()
            (rec / "2026-10-30/recording-abc/outside").symlink_to(root / "secret")
            bucket = BucketFake()
            with self.assertRaises(MigrationBlocked) as caught:
                upload_snapshot(client_json=root / "unused", settings_file=settings,
                                catalog=catalog, work_dir=work, receipt=root / "receipt",
                                recovery_file=root / "recovery",
                                transport=GCSArchiveTransport(bucket, bucket_name=TEST_BUCKET),
                                vault=ArchiveKeyVault(backend=KeychainFake()))
            self.assertEqual(str(caught.exception), "SOURCE_NOT_REGULAR")
            self.assertFalse(bucket.objects)

    def test_explicit_backup_opt_in_required_without_touching_gcs_or_keychain(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["backup", "--apply"]), 2)
        self.assertEqual(json.loads(err.getvalue())["error_code"],
                         "REAL_MEETING_UPLOAD_CONSENT_REQUIRED")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["backup", "--allow-real-meeting-data"]), 2)
        self.assertEqual(json.loads(err.getvalue())["error_code"], "EXPLICIT_APPLY_REQUIRED")


if __name__ == "__main__":
    unittest.main()
