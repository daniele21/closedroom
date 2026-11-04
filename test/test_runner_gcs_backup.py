"""Offline verification of the no-secrets GitHub Mac cold-backup entrypoint."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import run_gcs_backup_on_runner as cli


class MemoryKeychain:
    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}
    def get_password(self, service: str, account: str):
        return self.items.get((service, account))
    def set_password(self, service: str, account: str, password: str):
        self.items[(service, account)] = password


class RunnerGCSBackupTests(unittest.TestCase):
    def test_exact_source_checkout_cli_import_works_without_root_on_pythonpath(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH="src")
        p = subprocess.run(
            [sys.executable, "-P", "scripts/run_gcs_backup_on_runner.py", "--help"],
            cwd=root, env=env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("preflight", p.stdout)

    def test_synthetic_recovery_keychain_roundtrip_proves_writable(self):
        class WritableKeychain(MemoryKeychain):
            def delete_password(self, service, account):
                self.items.pop((service, account), None)
        store = WritableKeychain()
        cli.verify_recovery_keychain_writable(store)
        self.assertEqual(store.items, {})
        store.items[(cli.CODE_SERVICE, cli.CODE_ACCOUNT)] = "existing"
        with self.assertRaises(cli.MigrationBlocked) as e:
            cli.verify_recovery_keychain_writable(store)
        self.assertEqual(str(e.exception), "RECOVERY_CODE_ALREADY_STORED")

    def test_nonwritable_recovery_keychain_blocks_before_upload(self):
        class ReadOnlyKeychain(MemoryKeychain):
            def set_password(self, service, account, value):
                raise OSError("private OS error; never emit to CI")
        with self.assertRaises(cli.MigrationBlocked) as e:
            cli.verify_recovery_keychain_writable(ReadOnlyKeychain())
        self.assertEqual(str(e.exception), "RECOVERY_KEYCHAIN_NOT_WRITABLE")

    def test_preflight_fails_closed_on_unapproved_runner(self):
        with mock.patch.object(cli.sys, "platform", "linux"):
            with self.assertRaises(cli.MigrationBlocked) as error:
                cli.preflight()
        self.assertEqual(str(error.exception), "UNAPPROVED_RUNNER_HOST")

    def test_headless_backup_only_prints_sanitized_status_and_keeps_recovery_secret(self):
        secrets = "CR1-VERY_SECRET_NEVER_SEND_TO_ACTION_LOGS"
        keychain = MemoryKeychain()
        with mock.patch.object(cli, "preflight", return_value={"status": "preflight_pass"}), \
                mock.patch.object(cli, "upload_snapshot", return_value=(
                    {"status": "cold_snapshot_uploaded_pending_restore", "file_count": 22}, secrets,
                )), mock.patch.object(cli, "native_macos_keychain", return_value=keychain):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["backup"]), 0)
        raw = out.getvalue()
        self.assertNotIn(secrets, raw)
        self.assertNotIn("CR1-", raw)
        data = json.loads(raw)
        self.assertTrue(data["recovery_code_stored_in_native_keychain"])
        self.assertFalse(data["remote_restore_verified"])
        self.assertEqual(keychain.get_password(cli.CODE_SERVICE, cli.CODE_ACCOUNT), secrets)

    def test_keychain_failure_never_prints_recovery_code(self):
        secrets = "CR1-VERY_SECRET_NEVER_SEND_TO_ACTION_LOGS"
        class BrokenKeychain(MemoryKeychain):
            def set_password(self, service, account, password):
                raise RuntimeError("SECRET-SDK-ERROR")
        with mock.patch.object(cli, "preflight", return_value={}), \
                mock.patch.object(cli, "upload_snapshot", return_value=(
                    {"status": "cold_snapshot_uploaded_pending_restore", "file_count": 22}, secrets,
                )), mock.patch.object(cli, "native_macos_keychain", return_value=BrokenKeychain()):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(cli.main(["backup"]), 2)
        self.assertEqual(
            json.loads(stderr.getvalue())["error_code"],
            "RUNNER_BACKUP_FAILED_CHECK_LOCAL_PRIVATE_LOGS",
        )
        self.assertNotIn(secrets, stderr.getvalue())
        self.assertNotIn("SECRET-SDK-ERROR", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
