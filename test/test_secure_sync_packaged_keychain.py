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
    MacKeychain, NativeKeychainError, NativeVaultProbeBackend,
    VAULT_PROBE_SERVICE, LOCAL_VAULT_PROBE_SERVICE, _SecurityAPI,
)
from local_asr_server.macos_keychain_probe import (
    CHILD_COMMAND, COMMAND, VAULT_COMMAND, VAULT_CHILD_COMMAND,
    LOCAL_COMMAND, LOCAL_CHILD_COMMAND,
    dispatch_keychain_probe, run_synthetic_keychain_smoke,
    run_native_vault_backend_smoke,
)


class FakeSecurity:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_read = False
        self.fail_write = False
        self.fail_after_add = False
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
        if self.fail_after_add:
            raise NativeKeychainError("Synthetic post-add readback failure")

    def update(self, account: str, secret: bytes) -> None:
        if self.fail_write or account not in self.data:
            raise NativeKeychainError("synthetic update error")
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


class DataProtectionKeychainContractTests(unittest.TestCase):
    def test_protected_probe_selects_data_protection_on_every_query(self) -> None:
        """The qualifier is shared by get/add/update/delete via _query."""
        class FakeCF:
            def __init__(self):
                self.calls = []

            def CFDictionarySetValue(self, query, key, value):
                self.calls.append((query, key, value))

        vault = _SecurityAPI.__new__(_SecurityAPI)
        vault.service = VAULT_PROBE_SERVICE
        vault.cf = FakeCF()
        vault._const = {"kSecUseDataProtectionKeychain": "DPK"}
        vault._true = True
        vault._configure_query("test-query")
        self.assertEqual(vault.cf.calls, [("test-query", "DPK", True)])

        legacy = _SecurityAPI.__new__(_SecurityAPI)
        legacy.service = "com.closedroom.app.secure-sync-probe.v1"
        legacy.cf = FakeCF()
        legacy._const = vault._const
        legacy._true = True
        legacy._configure_query("legacy-query")
        self.assertEqual(legacy.cf.calls, [])

    def test_query_and_crud_share_protected_selector_with_no_fallback(self) -> None:
        import inspect
        from local_asr_server.macos_keychain_native import _SecurityAPI
        source = inspect.getsource(_SecurityAPI)
        self.assertIn('"kSecUseDataProtectionKeychain"', source)
        self.assertIn('"kSecAttrAccessibleWhenUnlockedThisDeviceOnly"', source)
        self.assertIn("self._configure_query(q)", source)
        for operation in ("get", "add", "update", "delete"):
            self.assertIn(f"def {operation}(", source)
        self.assertNotIn("kSecAttrSynchronizable", source)


class NativeVaultProbeBackendTests(unittest.TestCase):
    def test_explicit_local_backend_isolated_and_never_crosses_service(self):
        api = FakeSecurity()
        backend = NativeVaultProbeBackend(local_development=True, _test_api=api)
        account = "a" * 32 + ":master"
        backend.set_password(LOCAL_VAULT_PROBE_SERVICE, account, "test")
        self.assertEqual(backend.get_password(LOCAL_VAULT_PROBE_SERVICE, account), "test")
        with self.assertRaises(NativeKeychainError):
            backend.get_password(VAULT_PROBE_SERVICE, account)
        with self.assertRaises(NativeKeychainError):
            NativeVaultProbeBackend(_test_api=api).get_password(LOCAL_VAULT_PROBE_SERVICE, account)
        backend.delete_password(LOCAL_VAULT_PROBE_SERVICE, account)
        self.assertFalse(api.data)

    def test_local_probe_dispatch_requires_explicit_command(self):
        with patch("local_asr_server.macos_keychain_probe.run_native_vault_backend_smoke") as run:
            self.assertTrue(dispatch_bundled_module(["ClosedRoom", LOCAL_COMMAND]))
            run.assert_called_once_with(local_development=True)
        with self.assertRaises(SystemExit):
            dispatch_bundled_module(["ClosedRoom", LOCAL_CHILD_COMMAND, "wrong"])

    def test_local_probe_child_proves_updated_secret_and_separate_schema(self):
        import base64
        api = FakeSecurity()
        backend = NativeVaultProbeBackend(local_development=True, _test_api=api)
        challenge = b"z" * 32
        def fake_child(args, **kwargs):
            self.assertEqual(args[1], LOCAL_CHILD_COMMAND)
            key = base64.b64decode(backend.get_password(LOCAL_VAULT_PROBE_SERVICE, args[2]))
            return type("Child", (), {"returncode": 0,
                "stdout": hmac.digest(key, challenge, hashlib.sha256).hex()})()
        out = io.StringIO()
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.NativeVaultProbeBackend", return_value=backend) as factory,
            patch("local_asr_server.macos_keychain_probe.secrets.token_bytes", side_effect=[b"a"*32, b"b"*32, challenge]),
            patch("local_asr_server.macos_keychain_probe.subprocess.run", side_effect=fake_child),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(run_native_vault_backend_smoke(local_development=True), 0)
        factory.assert_called_once_with(local_development=True)
        self.assertEqual(json.loads(out.getvalue())["schema"], "closedroom.local-development-vault-probe/v1")
        self.assertFalse(api.data)

    def test_create_update_read_clear_and_delete(self) -> None:
        api = FakeSecurity()
        store = NativeVaultProbeBackend(_test_api=api)
        account = "a" * 32 + ":ledger-prepare"
        self.assertIsNone(store.get_password(VAULT_PROBE_SERVICE, account))
        store.set_password(VAULT_PROBE_SERVICE, account, "first")
        store.set_password(VAULT_PROBE_SERVICE, account, "next")
        self.assertEqual(store.get_password(VAULT_PROBE_SERVICE, account), "next")
        store.set_password(VAULT_PROBE_SERVICE, account, "")
        self.assertEqual(store.get_password(VAULT_PROBE_SERVICE, account), "")
        store.delete_password(VAULT_PROBE_SERVICE, account)
        self.assertIsNone(store.get_password(VAULT_PROBE_SERVICE, account))

    def test_service_account_and_size_restrictions(self) -> None:
        store = NativeVaultProbeBackend(_test_api=FakeSecurity())
        for name in ("a" * 32, "../vault:master", "A" * 32 + ":master",
                     "a" * 32 + ":unknown", "a" * 32 + ":epoch:01",
                     "a" * 32 + ":epoch:1", "a" * 32 + ":epoch:1000000"):
            with self.subTest(name=name), self.assertRaises(NativeKeychainError):
                store.set_password(VAULT_PROBE_SERVICE, name, "x")
        with self.assertRaises(NativeKeychainError):
            store.set_password("com.closedroom.app.secure-sync.v1",
                               "a" * 32 + ":master", "x")
        with self.assertRaises(NativeKeychainError):
            store.set_password(VAULT_PROBE_SERVICE, "a" * 32 + ":master", "x" * 5000)
        store.set_password(VAULT_PROBE_SERVICE, "a" * 32 + ":epoch:2", "ok")
        self.assertEqual(store.get_password(VAULT_PROBE_SERVICE,
                                            "a" * 32 + ":epoch:2"), "ok")

    def test_native_failure_corruption_and_nonmac_no_fallback(self) -> None:
        api = FakeSecurity()
        store = NativeVaultProbeBackend(_test_api=api)
        account = "b" * 32 + ":master"
        api.fail_write = True
        with self.assertRaises(NativeKeychainError):
            store.set_password(VAULT_PROBE_SERVICE, account, "new")
        api.fail_write = False
        api.data[account] = b"\xff"
        with self.assertRaises(NativeKeychainError):
            store.get_password(VAULT_PROBE_SERVICE, account)
        api.data[account] = b"valid"
        api.fail_write = True
        with self.assertRaises(NativeKeychainError):
            store.set_password(VAULT_PROBE_SERVICE, account, "new")
        self.assertEqual(api.data[account], b"valid")
        with patch("local_asr_server.macos_keychain_native.sys.platform", "linux"):
            with self.assertRaises(NativeKeychainError):
                NativeVaultProbeBackend()

    def test_second_process_updated_secret_and_probe_cleanup(self) -> None:
        api = FakeSecurity()
        backend = NativeVaultProbeBackend(_test_api=api)
        vault_id = "a" * 32
        challenge = b"z" * 32
        original = b"a" * 32
        replacement = b"b" * 32

        def fake_child(args: list[str], **_: object):
            self.assertEqual(args[1:3], [VAULT_CHILD_COMMAND, vault_id + ":master"])
            self.assertEqual(bytes.fromhex(args[3]), challenge)
            stored = backend.get_password(VAULT_PROBE_SERVICE, vault_id + ":master")
            proof = hmac.digest(base64.b64decode(stored), challenge, hashlib.sha256).hex()
            return type("Child", (), {"returncode": 0, "stdout": proof})()

        import base64
        stdout = io.StringIO()
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.NativeVaultProbeBackend",
                  return_value=backend),
            patch("local_asr_server.macos_keychain_probe.secrets.token_hex",
                  return_value=vault_id),
            patch("local_asr_server.macos_keychain_probe.secrets.token_bytes",
                  side_effect=[original, replacement, challenge]),
            patch("local_asr_server.macos_keychain_probe.subprocess.run",
                  side_effect=fake_child),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(run_native_vault_backend_smoke(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["updated_item"], True)
        self.assertEqual(api.data, {})
        self.assertEqual(set(api.deleted), {
            vault_id + ":master", vault_id + ":ledger-prepare",
        })

    def test_partial_add_failure_cleans_own_synthetic_item(self) -> None:
        api = FakeSecurity()
        api.fail_after_add = True
        backend = NativeVaultProbeBackend(_test_api=api)
        vault_id = "d" * 32
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.NativeVaultProbeBackend",
                  return_value=backend),
            patch("local_asr_server.macos_keychain_probe.secrets.token_hex",
                  return_value=vault_id),
        ):
            with self.assertRaises(NativeKeychainError):
                run_native_vault_backend_smoke()
        self.assertEqual(api.data, {})
        self.assertIn(vault_id + ":master", api.deleted)

    def test_failed_child_probe_deletes_only_created_records(self) -> None:
        api = FakeSecurity()
        backend = NativeVaultProbeBackend(_test_api=api)
        vault_id = "b" * 32
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.NativeVaultProbeBackend",
                  return_value=backend),
            patch("local_asr_server.macos_keychain_probe.secrets.token_hex",
                  return_value=vault_id),
            patch("local_asr_server.macos_keychain_probe.subprocess.run",
                  return_value=type("Child", (), {"returncode": 2, "stdout": ""})()),
        ):
            with self.assertRaises(NativeKeychainError):
                run_native_vault_backend_smoke()
        self.assertEqual(api.data, {})
        api.data[vault_id + ":master"] = b"preexisting"
        with (
            patch("local_asr_server.macos_keychain_probe._require_bundle"),
            patch("local_asr_server.macos_keychain_probe.NativeVaultProbeBackend",
                  return_value=backend),
            patch("local_asr_server.macos_keychain_probe.secrets.token_hex",
                  return_value=vault_id),
        ):
            with self.assertRaises(NativeKeychainError):
                run_native_vault_backend_smoke()
        self.assertEqual(api.data[vault_id + ":master"], b"preexisting")


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
        with self.assertRaises(SystemExit):
            dispatch_bundled_module(["ClosedRoom", VAULT_COMMAND, "extraneous"])
        with self.assertRaises(SystemExit):
            dispatch_bundled_module(["ClosedRoom", VAULT_CHILD_COMMAND, "wrong"])

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


class PackagedLocalSigningPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        from pathlib import Path
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        spec = importlib.util.spec_from_file_location(
            "keychain_probe_driver_test", scripts / "probe_packaged_keychain.py",
        )
        cls.driver = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", [str(scripts), *sys.path]):
            spec.loader.exec_module(cls.driver)

    def test_missing_identity_refused_before_signing_or_build(self):
        with patch.object(self.driver.subprocess, "run") as run:
            for value in (None, "-", "ClosedRoom Local Development", "a"*39):
                with self.assertRaises(RuntimeError):
                    self.driver.validate_signing_identity(value)
            run.assert_not_called()

    def test_exact_local_identity_inventory_checked(self):
        from types import SimpleNamespace
        with patch.object(self.driver.subprocess, "run", return_value=SimpleNamespace(
            stdout='  1) ' + "A"*40 + ' "Local Dev"\n  1 valid identities found\n',
        )) as run:
            self.driver.validate_signing_identity("a"*40)
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                self.driver.validate_signing_identity("b"*40)
            self.assertEqual(run.call_args.args[0], ["security", "find-identity", "-v", "-p", "codesigning"])

    def test_actual_leaf_certificate_must_match_selected_identity(self):
        from pathlib import Path
        data = b"synthetic public certificate bytes"
        fingerprint = hashlib.sha1(data).hexdigest()
        def extract(args, **kwargs):
            self.assertEqual(args[:3], ["codesign", "-d", "--extract-certificates"])
            Path(args[3] + "0").write_bytes(data)
        with patch.object(self.driver.subprocess, "run", side_effect=extract):
            self.driver.validate_signing_identity(fingerprint, Path("/fake.app"))
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                self.driver.validate_signing_identity("c"*40, Path("/fake.app"))

    def test_dpk_does_not_rebuild_ad_hoc(self):
        from types import SimpleNamespace
        args = SimpleNamespace(root=".", app=None, build=True,
                               backend="data-protection", sign_identity=None)
        with (
            patch.object(self.driver, "parse_args", return_value=args),
            patch.object(self.driver.platform, "system", return_value="Darwin"),
            patch.object(self.driver.platform, "machine", return_value="arm64"),
            patch.object(self.driver.subprocess, "run", return_value=SimpleNamespace(stdout="a"*40)) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "Data Protection Keychain build blocked"):
                self.driver.main()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], ["git", "rev-parse", "HEAD"])


if __name__ == "__main__":
    unittest.main()
