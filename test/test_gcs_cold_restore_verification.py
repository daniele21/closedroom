"""Offline proof that a real GCS restore check is isolated and fail-closed."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from scripts import verify_closedroom_gcs_cold_restore as proof


class ColdRestoreProofTests(unittest.TestCase):
    def test_login_session_required_before_any_receipt_or_keychain_access(self):
        with mock.patch.object(proof.sys, "platform", "linux"), \
             mock.patch.object(proof, "_private_json") as receipt, \
             mock.patch.object(proof, "_read_code") as read_code:
            with self.assertRaises(proof.MigrationBlocked) as err:
                proof.verify_isolated_restore()
        self.assertEqual(str(err.exception), "TRUSTED_LOGIN_BROKER_REQUIRED")
        receipt.assert_not_called()
        read_code.assert_not_called()

    def test_foreign_bucket_blocked_before_recovery_code_read(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp)
            with mock.patch.object(proof.sys, "platform", "darwin"), \
                 mock.patch.dict(os.environ,
                                 {"CLOSEDROOM_TRUSTED_LOGIN_BROKER": "1",
                                  "GITHUB_ACTIONS": ""}), \
                 mock.patch.object(proof, "HOME_CONFIG", private), \
                 mock.patch.object(proof, "_private_json",
                                   return_value={"format": "closedroom-cold-snapshot-v1",
                                                 "asset": {"bucket": "unapproved"},
                                                 "summary": {"file_count": 3}}), \
                 mock.patch.object(proof, "_read_code") as read_code:
                with self.assertRaises(proof.MigrationBlocked) as err:
                    proof.verify_isolated_restore()
            self.assertEqual(str(err.exception), "RESTORE_BUCKET_MISMATCH")
            read_code.assert_not_called()

    def test_isolated_restore_passes_without_touching_originals(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            config = home / ".config/closedroom"
            config.mkdir(parents=True)
            originals = home / "originals"
            originals.mkdir()
            original_audio = originals / "mic.wav"
            original_audio.write_bytes(b"original recording content")
            scratch_targets = []

            def fake_restore(*, target, **kw):
                self.assertIsInstance(kw["vault"], proof.EphemeralRecoveryVault)
                self.assertNotEqual(target, originals)
                self.assertFalse(target.exists())
                scratch_targets.append(target.parent)
                (target / "catalog").mkdir(parents=True)
                with sqlite3.connect(target / "catalog/closedroom.db") as db:
                    db.execute("CREATE TABLE recordings (id TEXT)")
                    db.execute("CREATE TABLE transcriptions (id TEXT)")
                    db.execute("INSERT INTO recordings VALUES ('fixture')")
                    db.execute("INSERT INTO transcriptions VALUES ('fixture')")
                    db.commit()
                (target / "recordings").mkdir()
                (target / "recordings/mic.wav").write_bytes(b"fixture")
                return {"status": "cold_snapshot_restored_to_isolated_directory",
                        "restored_files": 3}

            receipt = {
                "format": "closedroom-cold-snapshot-v1",
                "asset": {"bucket": "project-tests-498508-closedroom-test"},
                "summary": {"file_count": 3},
            }
            with mock.patch.object(proof.sys, "platform", "darwin"), \
                 mock.patch.dict(os.environ,
                                 {"CLOSEDROOM_TRUSTED_LOGIN_BROKER": "1",
                                  "GITHUB_ACTIONS": ""}), \
                 mock.patch.object(proof, "HOME_CONFIG", config), \
                 mock.patch.object(proof.Path, "home", return_value=home), \
                 mock.patch.object(proof, "_private_json", return_value=receipt), \
                 mock.patch.object(proof, "_read_code", return_value="CR1-" + "a" * 43), \
                 mock.patch.object(proof, "restore_snapshot", side_effect=fake_restore):
                result = proof.verify_isolated_restore()

            self.assertEqual(result["status"], "cold_snapshot_restored_verified_isolated")
            self.assertEqual(result["restored_files"], 3)
            self.assertEqual(result["recordings_rows"], 1)
            self.assertFalse(result["verified_on_second_mac"])
            self.assertFalse(result["independent_code_custody_verified"])
            self.assertFalse(result["originals_deleted"])
            self.assertEqual(original_audio.read_bytes(), b"original recording content")
            self.assertTrue(scratch_targets)
            self.assertFalse(scratch_targets[0].exists())

    def test_returned_restore_count_must_match_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            private = home / ".config"
            private.mkdir()
            receipt = {
                "format": "closedroom-cold-snapshot-v1",
                "asset": {"bucket": "project-tests-498508-closedroom-test"},
                "summary": {"file_count": 42},
            }
            with mock.patch.object(proof.sys, "platform", "darwin"), \
                 mock.patch.dict(os.environ,
                                 {"CLOSEDROOM_TRUSTED_LOGIN_BROKER": "1",
                                  "GITHUB_ACTIONS": ""}), \
                 mock.patch.object(proof, "HOME_CONFIG", private), \
                 mock.patch.object(proof.Path, "home", return_value=home), \
                 mock.patch.object(proof, "_private_json", return_value=receipt), \
                 mock.patch.object(proof, "_read_code", return_value="CR1-" + "a" * 43), \
                 mock.patch.object(proof, "restore_snapshot",
                                   return_value={
                                       "status": "cold_snapshot_restored_to_isolated_directory",
                                       "restored_files": 41,
                                   }):
                with self.assertRaises(proof.MigrationBlocked) as err:
                    proof.verify_isolated_restore()
            self.assertEqual(str(err.exception), "RESTORE_FILE_COUNT_MISMATCH")

    def test_password_or_sdk_error_never_appears_in_cli_output(self):
        with mock.patch.object(proof, "verify_isolated_restore",
                               side_effect=RuntimeError("private token path")):
            from contextlib import redirect_stderr
            import io
            buffer = io.StringIO()
            with redirect_stderr(buffer):
                self.assertEqual(proof.main(), 2)
        value = json.loads(buffer.getvalue())
        self.assertEqual(value["error_code"], "ISOLATED_RESTORE_FAILED")
        self.assertNotIn("private token", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
