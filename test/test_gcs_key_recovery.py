"""Local-only, fake-Keychain tests of portable archive recovery."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest

from local_asr_server.storage.key_recovery import (
    ArchiveKeyVault, ArchiveKeyUnavailable, RecoveryFailed,
    create_recovery_envelope, recover_key, key_fingerprint,
    load_recovery_file, save_recovery_file,
)


class FakeKeychain:
    def __init__(self):
        self.items = {}
    def get_password(self, service, account):
        return self.items.get((service, account))
    def set_password(self, service, account, value):
        self.items[(service, account)] = value


class ArchiveKeyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes(range(32))

    def test_portable_recovery_restores_same_key_into_new_keychain(self):
        first, second = FakeKeychain(), FakeKeychain()
        old = ArchiveKeyVault(first, fixture=True)
        new = ArchiveKeyVault(second, fixture=True)
        old.store_if_absent(self.key)
        envelope, code = create_recovery_envelope(old.load())
        self.assertNotIn(code, str(envelope))
        self.assertNotIn(self.key.hex(), str(envelope))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive-recovery.json'
            save_recovery_file(path, envelope)
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            copied = load_recovery_file(path)
            result = new.import_recovery(copied, code)
        self.assertEqual(result, self.key)
        self.assertEqual(new.load(), self.key)
        self.assertEqual(key_fingerprint(result), envelope['key_sha256'])
        self.assertNotEqual(first.items, {})
        self.assertNotEqual(second.items, {})
        self.assertEqual(new.import_recovery(envelope, code), self.key)

    def test_wrong_code_and_modified_ciphertext_fail_closed(self):
        envelope, code = create_recovery_envelope(self.key)
        altered_code = code[:-1] + ('A' if code[-1] != 'A' else 'B')
        with self.assertRaises(RecoveryFailed):
            recover_key(envelope, altered_code)
        changed = copy.deepcopy(envelope)
        data = list(changed['ciphertext'])
        data[15] = 'A' if data[15] != 'A' else 'B'
        changed['ciphertext'] = ''.join(data)
        with self.assertRaises(RecoveryFailed):
            recover_key(changed, code)

    def test_unrecognized_format_and_short_secret_rejected(self):
        envelope, code = create_recovery_envelope(self.key)
        for changed in (
            dict(envelope, format='v999'),
            dict(envelope, salt='abc'),
            dict(envelope, kdf='plaintext'),
            dict(envelope, key_sha256='wrong'),
            dict(envelope, unexpected='file'),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(RecoveryFailed):
                    recover_key(changed, code)
        with self.assertRaises(RecoveryFailed):
            recover_key(envelope, 'user-chosen-password')

    def test_recovery_cannot_overwrite_another_mac_key(self):
        vault = ArchiveKeyVault(FakeKeychain(), fixture=True)
        vault.store_if_absent(b'A' * 32)
        envelope, code = create_recovery_envelope(b'B' * 32)
        with self.assertRaises(ArchiveKeyUnavailable):
            vault.import_recovery(envelope, code)
        self.assertEqual(vault.load(), b'A' * 32)
        with self.assertRaises(ArchiveKeyUnavailable):
            vault.store_if_absent(self.key)

    def test_export_no_overwrite_and_private_file(self):
        envelope, _ = create_recovery_envelope(self.key)
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / 'recovery.json'
            save_recovery_file(p, envelope)
            original = p.read_bytes()
            with self.assertRaises(FileExistsError):
                save_recovery_file(p, envelope)
            self.assertEqual(p.read_bytes(), original)
            p.chmod(0o644)
            with self.assertRaises(RecoveryFailed):
                load_recovery_file(p)
            p.chmod(0o600)
            evil = Path(root) / 'evil'
            evil.symlink_to(p)
            with self.assertRaises(RecoveryFailed):
                load_recovery_file(evil)
            with self.assertRaises(FileExistsError):
                save_recovery_file(evil, envelope)

    def test_native_backend_never_falls_back_on_non_mac(self):
        from unittest.mock import patch
        with patch('local_asr_server.storage.key_recovery.sys.platform', 'linux'):
            with self.assertRaises(ArchiveKeyUnavailable):
                ArchiveKeyVault()


if __name__ == '__main__':
    unittest.main()
