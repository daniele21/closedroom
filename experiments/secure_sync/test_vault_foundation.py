"""Security proof cases; fake Keychain is not representative macOS validation."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from vault_manifest import (
    ManifestError, generate_owner_signing_key, new_manifest, new_vault_id,
    object_reference, public_key_bytes, sign_manifest, verify_manifest, verify_object,
)
from vault_keychain import KeychainError, MacKeychainVaultKeys, SERVICE


class FakeKeychain:
    def __init__(self):
        self.data = {}
        self.fail_write = False

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        if self.fail_write:
            raise OSError("synthetic Keychain failure")
        self.data[(service, name)] = value


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.owner = generate_owner_signing_key()
        self.pub = public_key_bytes(self.owner)
        self.vault = new_vault_id()
        self.genesis = sign_manifest(
            new_manifest(vault_id=self.vault, revision=0, previous=None), self.owner,
        )
        self.first = verify_manifest(self.genesis, self.pub)

    def test_signed_genesis_and_contiguous_update(self):
        nxt = sign_manifest(new_manifest(
            vault_id=self.vault, revision=1, previous=self.first.digest,
        ), self.owner)
        accepted = verify_manifest(nxt, self.pub, self.first)
        self.assertEqual(accepted.revision, 1)
        self.assertEqual(verify_manifest(nxt, self.pub, accepted), accepted)

    def test_invalid_signer_and_mutated_header_are_rejected(self):
        with self.assertRaises(ManifestError):
            verify_manifest(self.genesis, public_key_bytes(generate_owner_signing_key()))
        tampered = json.loads(self.genesis)
        tampered["manifest"]["key_epoch"] = 2
        with self.assertRaises(ManifestError):
            verify_manifest(json.dumps(tampered).encode("utf-8"), self.pub)

    def test_older_head_and_fork_are_rejected(self):
        nxt = new_manifest(vault_id=self.vault, revision=1, previous=self.first.digest)
        accepted = verify_manifest(sign_manifest(nxt, self.owner), self.pub, self.first)
        with self.assertRaises(ManifestError):
            verify_manifest(self.genesis, self.pub, accepted)
        fork = new_manifest(
            vault_id=self.vault, revision=1, previous=self.first.digest,
            objects=[object_reference("a" * 32, b"ciphertext")],
        )
        with self.assertRaises(ManifestError):
            verify_manifest(sign_manifest(fork, self.owner), self.pub, accepted)

    def test_reject_unknown_future_and_skipped_versions(self):
        with self.assertRaises(ManifestError):
            sign_manifest({**new_manifest(
                vault_id=self.vault, revision=0, previous=None,
            ), "version": 2}, self.owner)
        skipped = sign_manifest(new_manifest(
            vault_id=self.vault, revision=2, previous="f" * 64,
        ), self.owner)
        with self.assertRaises(ManifestError):
            verify_manifest(skipped, self.pub, self.first)
        with self.assertRaises(ManifestError):
            verify_manifest(skipped, self.pub)

    def test_signed_object_digest_binds_encrypted_content(self):
        reference = object_reference("a" * 32, b"encrypted-bytes")
        verify_object(reference, b"encrypted-bytes")
        with self.assertRaises(ManifestError):
            verify_object(reference, b"substituted")
        with self.assertRaises(ManifestError):
            new_manifest(
                vault_id=self.vault, revision=0, previous=None,
                objects=[reference, reference],
            )

    def test_duplicate_json_fields_are_rejected(self):
        duplicate = self.genesis[:-1] + b', "signature":"duplicate"}'
        with self.assertRaises(ManifestError):
            verify_manifest(duplicate, self.pub)


class KeychainTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeKeychain()
        self.keys = MacKeychainVaultKeys(_test_backend=self.backend)
        self.vault = "a" * 32

    def test_vault_key_is_random_nonoverwritable_and_restart_readable(self):
        original = self.keys.create(self.vault)
        self.assertEqual(len(original), 32)
        new_process = MacKeychainVaultKeys(_test_backend=self.backend)
        self.assertEqual(new_process.load(self.vault), original)
        with self.assertRaises(KeychainError):
            new_process.create(self.vault)

    def test_separate_owner_identity_and_corrupt_material(self):
        signer = self.keys.create_owner_signer(self.vault)
        self.assertEqual(
            signer.public_key().public_bytes_raw(),
            MacKeychainVaultKeys(_test_backend=self.backend).load_owner_signer(self.vault)
                .public_key().public_bytes_raw(),
        )
        with self.assertRaises(KeychainError):
            self.keys.create_owner_signer(self.vault)
        self.backend.data[(SERVICE, self.vault + ":owner-signing")] = "garbled!"
        with self.assertRaises(KeychainError):
            self.keys.load_owner_signer(self.vault)

    def test_trusted_pin_checkpoint_survive_restart_and_reject_replay(self):
        signer = self.keys.create_owner_signer(self.vault)
        self.keys.pin_authenticated_owner(self.vault, signer.public_key().public_bytes_raw())
        first_doc = sign_manifest(new_manifest(
            vault_id=self.vault, revision=0, previous=None,
        ), signer)
        first = self.keys.accept_signed_head(self.vault, first_doc)
        nxt = sign_manifest(new_manifest(
            vault_id=self.vault, revision=1, previous=first.digest,
        ), signer)
        expected = self.keys.accept_signed_head(self.vault, nxt)
        restarted = MacKeychainVaultKeys(_test_backend=self.backend)
        self.assertEqual(restarted.load_checkpoint(self.vault), expected)
        self.assertEqual(restarted.accept_signed_head(self.vault, nxt), expected)
        with self.assertRaises(ManifestError):
            restarted.accept_signed_head(self.vault, first_doc)
        with self.assertRaises(KeychainError):
            self.keys.pin_authenticated_owner(self.vault, b"x" * 32)

    def test_missing_anchor_corrupt_checkpoint_and_backend_error_fail_closed(self):
        signer = self.keys.create_owner_signer(self.vault)
        document = sign_manifest(new_manifest(
            vault_id=self.vault, revision=0, previous=None,
        ), signer)
        with self.assertRaises(KeychainError):
            self.keys.accept_signed_head(self.vault, document)
        self.keys.pin_authenticated_owner(self.vault, signer.public_key().public_bytes_raw())
        self.backend.data[(SERVICE, self.vault + ":checkpoint")] = '{"revision":0}'
        with self.assertRaises(KeychainError):
            self.keys.accept_signed_head(self.vault, document)
        self.backend.fail_write = True
        with self.assertRaises(KeychainError):
            self.keys.create("b" * 32)

    def test_no_insecure_linux_fallback_and_bad_identifiers(self):
        with patch("vault_keychain.sys.platform", "linux"):
            with self.assertRaises(KeychainError):
                MacKeychainVaultKeys()
        with self.assertRaises(KeychainError):
            self.keys.create("../bad")


if __name__ == "__main__":
    unittest.main()
