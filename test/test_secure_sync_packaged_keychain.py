from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import json
import sys
import unittest
from unittest.mock import patch

from local_asr_server.bundled_module_dispatch import dispatch_bundled_module
from local_asr_server.macos_keychain_native import (
    MacKeychain, NativeKeychainError, _SecurityAPI,
)
from local_asr_server.macos_keychain_probe import (
    CHILD_COMMAND, COMMAND, dispatch_keychain_probe, run_synthetic_keychain_smoke,
)


class FakeSecurity:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_read = False
        self.fail_write = False
        self.deleted: list[str] = []

    def get(self, account: str) -> bytes | None:
        if self.fail_read:
            raise NativeKeychainError("synthetic read failure")
        return self.data.get(account)

    def add(self, account: str, secret: bytes) -> None:
        if self.fail_write:
            raise NativeKeychainError("synthetic OSStatus")
        if account in self.data:
            raise NativeKeychainError("synthetic duplicate")
        self.data[account] = secret

    def delete(self, account: str) -> None:
        self.deleted.append(account)
        self.data.pop(account, None)


class NativeKeychainAdapterTests(unittest.TestCase):
    def test_bad_identifiers_and_non_32_byte_keys_fail_closed(self) -> None:
        store = MacKeychain(_test_api=FakeSecurity())
        for account in ("../secrets", "a" * 31, "A" * 32, ""):
            with self.assertRaises(NativeKeychainError):
                store.load(account)
        with self.assertRaises(NativeKeychainError):
            store.create("a" * 32, b"short")

    def test_create_read_delete_and_duplicate_rejection(self) -> None:
        api = FakeSecurity()
        a = MacKeychain(_test_api=api)
        b = MacKeychain(_test_api=api)
        account = "a" * 32
        secret = b"\x01" * 32
        a.create(account, secret)
        self.assertEqual(b.load(account), secret)
        with self.assertRaises(NativeKeychainError):
            b.create(account, b"\x02" * 32)
        self.assertEqual(a.load(account), secret)
        b.delete(account)
        self.assertIsNone(a.load(account))

    def test_corrupt_key_and_backend_errors_fail_closed(self) -> None:
        api = FakeSecurity()
        store = MacKeychain(_test_api=api)
        account = "b" * 32
        api.data[account] = b"bad"
        with self.assertRaises(NativeKeychainError):
            store.load(account)
        api.fail_read = True
        with self.assertRaises(NativeKeychainError):
            store.load(account)
        api.fail_read = False
        api.fail_write = True
        with self.assertRaises(NativeKeychainError):
            store.create("c" * 32, b"x" * 32)

    def test_no_nonmac_file_or_command_fallback(self) -> None:
        with patch("local_asr_server.macos_keychain_native.sys.platform", "linux"):
            with self.assertRaises(NativeKeychainError):
                _SecurityAPI()

    def test_background_ci_cannot_claim_gui_keychain_success(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        ci = (root / ".github" / "ci" / "local-test.sh").read_text(encoding="utf-8")
        self.assertIn('test_*.py', ci)
        self.assertIn("KEYCHAIN_REAL_ENVIRONMENT=NOT_RUN", ci)
        self.assertIn("scripts/probe_packaged_keychain.py --build", ci)
        self.assertNotIn(
            '"${SECURE_SYNC_PY[@]}" experiments/secure_sync/macos_keychain_probe.py', ci,
        )


class SignedBundleDiagnosticTests(unittest.TestCase):
    def test_normal_app_and_unrelated_commands_are_not_intercepted(self) -> None:
        self.assertFalse(dispatch_keychain_probe(["ClosedRoom"]))
        self.assertFalse(dispatch_keychain_probe(["ClosedRoom", "serve"]))
        self.assertFalse(dispatch_bundled_module(["ClosedRoom", "--not-a-diagnostic"]))

    def test_diagnostic_is_bundle_only_and_arguments_strict(self) -> None:
        with patch("local_asr_server.macos_keychain_probe.sys.platform", "linux"):
            with self.assertRaises(NativeKeychainError):
                dispatch_bundled_module(["ClosedRoom", COMMAND])
        with self.assertRaises(SystemExit):
            dispatch_bundled_module(["ClosedRoom", COMMAND, "extraneous"])
        with self.assertRaises(SystemExit):
            dispatch_bundled_module(["ClosedRoom", CHILD_COMMAND, "wrong"])

    def test_packaged_parent_second_process_challenge_and_cleanup(self) -> None:
        api = FakeSecurity()
        store = MacKeychain(_test_api=api)
        account = "a" * 32
        key = bytes(range(32))
        challenge = bytes(range(32, 64))

        def fake_child(args: list[str], **_: object):
            self.assertEqual(args[1:3], [CHILD_COMMAND, account])
            self.assertEqual(bytes.fromhex(args[3]), challenge)
            proof = hmac.digest(store.load(account), challenge, hashlib.sha256).hex()
            return type("Child", (), {"returncode": 0, "stdout": proof})()

        stdout = io.StringIO()
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.MacKeychain", return_value=store),
            patch("local_asr_server.macos_keychain_probe.secrets.token_hex", return_value=account),
            patch("local_asr_server.macos_keychain_probe.secrets.token_bytes", side_effect=[key, challenge]),
            patch("local_asr_server.macos_keychain_probe.subprocess.run", side_effect=fake_child),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(run_synthetic_keychain_smoke(), 0)
        outcome = json.loads(stdout.getvalue())
        self.assertEqual(outcome["status"], "pass")
        self.assertTrue(outcome["cleanup"])
        self.assertEqual(api.deleted, [account])
        self.assertNotIn(account, api.data)

    def test_child_failure_still_cleans_up_and_no_false_pass(self) -> None:
        api = FakeSecurity()
        store = MacKeychain(_test_api=api)
        account = "b" * 32
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.MacKeychain", return_value=store),
            patch("local_asr_server.macos_keychain_probe.secrets.token_hex", return_value=account),
            patch("local_asr_server.macos_keychain_probe.secrets.token_bytes", side_effect=[b"x" * 32, b"y" * 32]),
            patch("local_asr_server.macos_keychain_probe.subprocess.run", return_value=type("Child", (), {"returncode": 2, "stdout": ""})()),
        ):
            with self.assertRaises(NativeKeychainError):
                run_synthetic_keychain_smoke()
        self.assertEqual(api.deleted, [account])
        self.assertNotIn(account, api.data)

    def test_collision_never_deletes_preexisting_secret(self) -> None:
        api = FakeSecurity()
        account = "c" * 32
        api.data[account] = b"x" * 32
        store = MacKeychain(_test_api=api)
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.MacKeychain", return_value=store),
            patch("local_asr_server.macos_keychain_probe.secrets.token_hex", return_value=account),
            patch("local_asr_server.macos_keychain_probe.secrets.token_bytes", return_value=b"y" * 32),
        ):
            with self.assertRaises(NativeKeychainError):
                run_synthetic_keychain_smoke()
        self.assertEqual(api.data[account], b"x" * 32)
        self.assertEqual(api.deleted, [])


if __name__ == "__main__":
    unittest.main()
