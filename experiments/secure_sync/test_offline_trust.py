"""Security tests for offline recovery and owner-authorized read-only pairing.

Synthetic keys only. Test state is in memory and is NOT durable cross-process
authorization, browser UX confirmation or a second physical Mac restore.
"""
from __future__ import annotations

import base64
import json
import unittest
from dataclasses import replace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from device_pairing import (
    PairingError, authorize_readonly_device, comparison_code,
    create_device_request, receive_readonly_device,
)
from recovery_capsule import (
    RecoveryError, create_recovery_capsule, generate_recovery_code,
    open_recovery_capsule,
)
from secure_sync import open_snapshot, seal_snapshot, transcript_snapshot
from vault_manifest import (
    TrustedCheckpoint, generate_owner_signing_key, new_manifest, new_vault_id,
    public_key_bytes, sign_manifest, verify_manifest,
)

NOW = 1_795_000_000


class OfflineTrustTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_id = new_vault_id()
        self.vault_key = bytes(range(32))
        self.owner = generate_owner_signing_key()
        self.owner_pub = public_key_bytes(self.owner)
        self.checkpoint = verify_manifest(
            sign_manifest(
                new_manifest(vault_id=self.vault_id, revision=0, previous=None),
                self.owner,
            ),
            self.owner_pub,
        )
        self.recovery_code = generate_recovery_code()
        self.capsule = create_recovery_capsule(
            self.vault_id, self.vault_key, self.owner,
            self.checkpoint, self.recovery_code,
        )

    def _pending(self):
        return create_device_request(self.vault_id, now=NOW)

    def _approve(self, pending, *, now=NOW, owner=None, checkpoint=None, code=None, approved=True):
        if code is None:
            code = comparison_code(pending.request, now=now)
        return authorize_readonly_device(
            pending.request, owner or self.owner, self.vault_key,
            checkpoint or self.checkpoint,
            manually_compared_code=code, explicit_approval=approved, now=now,
        )

    def test_independent_recovery_restores_owner_vault_and_checkpoint(self):
        restored = open_recovery_capsule(
            self.capsule, self.recovery_code,
            expected_vault_id=self.vault_id,
            expected_owner_public=self.owner_pub,
            minimum_checkpoint=self.checkpoint,
        )
        self.assertEqual(restored.vault_id, self.vault_id)
        self.assertEqual(restored.vault_key, self.vault_key)
        self.assertEqual(restored.owner_public, self.owner_pub)
        self.assertEqual(restored.checkpoint, self.checkpoint)
        self.assertEqual(public_key_bytes(restored.owner_signer), self.owner_pub)
        # Signing identity remains usable without original Mac/Keychain.
        signature = restored.owner_signer.sign(b"synthetic challenge")
        restored.owner_signer.public_key().verify(signature, b"synthetic challenge")

    def test_recovery_secret_is_independent_and_never_in_capsule(self):
        self.assertTrue(self.recovery_code.startswith("CR1-"))
        self.assertEqual(len(self.recovery_code), 56)
        self.assertNotIn(self.recovery_code.encode(), self.capsule)
        self.assertNotIn(base64.b64encode(self.vault_key), self.capsule)
        self.assertNotIn(base64.b64encode(self.owner.private_bytes_raw()), self.capsule)
        self.assertNotEqual(generate_recovery_code(), self.recovery_code)

    def test_wrong_recovery_code_or_low_entropy_input_fails(self):
        with self.assertRaises(RecoveryError):
            open_recovery_capsule(self.capsule, generate_recovery_code())
        for weak in ("password", "CR1-" + "A" * 51, "CR1-" + "!" * 52, "", "CR1-" + "A" * 52):
            with self.subTest(weak=weak[:9]):
                with self.assertRaises(RecoveryError):
                    open_recovery_capsule(self.capsule, weak)

    def test_recovery_tampering_and_unknown_schema_fail_closed(self):
        document = json.loads(self.capsule)
        for name, value in (
            ("version", 2),
            ("vault_id", "f" * 32),
            ("salt", base64.b64encode(bytes(16)).decode()),
            ("nonce", base64.b64encode(bytes(12)).decode()),
        ):
            tampered = dict(document)
            tampered[name] = value
            with self.subTest(name=name), self.assertRaises(RecoveryError):
                open_recovery_capsule(json.dumps(tampered).encode(), self.recovery_code)
        with self.assertRaises(RecoveryError):
            open_recovery_capsule(b'{"format":1,"format":2}', self.recovery_code)
        with self.assertRaises(RecoveryError):
            open_recovery_capsule(self.capsule + b"x" * 4096, self.recovery_code)

    def test_recovery_missing_pin_and_checkpoint_freshness_are_explicit(self):
        with self.assertRaises(RecoveryError):
            open_recovery_capsule(
                self.capsule, self.recovery_code,
                expected_vault_id="e" * 32,
            )
        with self.assertRaises(RecoveryError):
            open_recovery_capsule(
                self.capsule, self.recovery_code,
                expected_owner_public=public_key_bytes(generate_owner_signing_key()),
            )
        newer = TrustedCheckpoint(
            self.vault_id, self.checkpoint.revision + 1,
            "a" * 64, self.checkpoint.key_epoch,
        )
        with self.assertRaises(RecoveryError):
            open_recovery_capsule(self.capsule, self.recovery_code, minimum_checkpoint=newer)
        conflicting = replace(self.checkpoint, digest="b" * 64)
        with self.assertRaises(RecoveryError):
            open_recovery_capsule(self.capsule, self.recovery_code, minimum_checkpoint=conflicting)

    def test_recovery_rejects_bad_owner_and_checkpoint_before_encrypting(self):
        with self.assertRaises(RecoveryError):
            create_recovery_capsule(
                self.vault_id, self.vault_key, self.owner,
                replace(self.checkpoint, vault_id="f" * 32), self.recovery_code,
            )
        with self.assertRaises(RecoveryError):
            create_recovery_capsule(
                self.vault_id, b"short", self.owner, self.checkpoint, self.recovery_code,
            )

    def test_pairing_returns_only_readonly_key_and_verified_checkpoint(self):
        pending = self._pending()
        displayed_new_mac = comparison_code(pending.request, now=NOW)
        displayed_owner = comparison_code(pending.request, now=NOW)
        self.assertEqual(displayed_new_mac, displayed_owner)
        self.assertEqual(len(displayed_new_mac), 8)
        approval = self._approve(pending, code=displayed_owner)
        result = receive_readonly_device(
            pending, approval, independently_authenticated_owner=self.owner_pub, now=NOW,
        )
        self.assertEqual(result.permission, "read_only")
        self.assertEqual(result.vault_key, self.vault_key)
        self.assertEqual(result.owner_public, self.owner_pub)
        self.assertEqual(result.checkpoint, self.checkpoint)
        snapshot = transcript_snapshot({"id": "synthetic-1", "text": "Private example"})
        envelope = seal_snapshot(snapshot, self.vault_key)
        self.assertEqual(open_snapshot(envelope, result.vault_key), snapshot)
        # Grant never includes owner signing secret or plaintext vault key.
        self.assertNotIn(base64.b64encode(self.vault_key), approval)
        self.assertNotIn(base64.b64encode(self.owner.private_bytes_raw()), approval)

    def test_pairing_requires_manual_comparison_and_explicit_permission(self):
        pending = self._pending()
        for code, approved in (("", True), ("00000000", True), ("", False)):
            with self.subTest(code=code, approved=approved), self.assertRaises(PairingError):
                self._approve(pending, code=code, approved=approved)
        with self.assertRaises(PairingError):
            self._approve(pending, approved=False)

    def test_pairing_expires_and_rejects_future_or_modified_requests(self):
        pending = self._pending()
        with self.assertRaises(PairingError):
            comparison_code(pending.request, now=NOW + 301)
        with self.assertRaises(PairingError):
            self._approve(pending, now=NOW + 301, code="12345678")
        approval = self._approve(pending)
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, approval, independently_authenticated_owner=self.owner_pub, now=NOW + 301)
        tampered = json.loads(pending.request)
        tampered["expires_at"] += 3600
        with self.assertRaises(PairingError):
            comparison_code(json.dumps(tampered).encode(), now=NOW)
        tampered = json.loads(pending.request)
        tampered["issued_at"] = NOW + 100
        with self.assertRaises(PairingError):
            comparison_code(json.dumps(tampered).encode(), now=NOW)

    def test_pairing_wrong_owner_key_signer_recipient_or_nonce_fails(self):
        pending = self._pending()
        approval = self._approve(pending)
        with self.assertRaises(PairingError):
            receive_readonly_device(
                pending, approval,
                independently_authenticated_owner=public_key_bytes(generate_owner_signing_key()), now=NOW,
            )
        impostor = self._approve(pending, owner=generate_owner_signing_key())
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, impostor, independently_authenticated_owner=self.owner_pub, now=NOW)
        different_request = self._pending()
        with self.assertRaises(PairingError):
            receive_readonly_device(different_request, approval, independently_authenticated_owner=self.owner_pub, now=NOW)
        tampered = json.loads(approval)
        tampered["grant"]["device_id"] = "f" * 32
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, json.dumps(tampered).encode(), independently_authenticated_owner=self.owner_pub, now=NOW)
        tampered = json.loads(approval)
        tampered["grant"]["ciphertext"] = base64.b64encode(b"x" * 48).decode()
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, json.dumps(tampered).encode(), independently_authenticated_owner=self.owner_pub, now=NOW)

    def test_pairing_replay_is_rejected_in_existing_pending_session(self):
        pending = self._pending()
        approval = self._approve(pending)
        receive_readonly_device(pending, approval, independently_authenticated_owner=self.owner_pub, now=NOW)
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, approval, independently_authenticated_owner=self.owner_pub, now=NOW)

    def test_pairing_stale_or_conflicting_checkpoint_is_rejected(self):
        pending = self._pending()
        approval = self._approve(pending)
        newer = replace(self.checkpoint, revision=1, digest="b" * 64)
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, approval, independently_authenticated_owner=self.owner_pub, now=NOW, minimum_checkpoint=newer)
        conflicting = replace(self.checkpoint, digest="c" * 64)
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, approval, independently_authenticated_owner=self.owner_pub, now=NOW, minimum_checkpoint=conflicting)

    def test_recovery_then_owner_authorization_without_original_device(self):
        # Simulated second Mac recovers owner secrets from the capsule + code.
        restored = open_recovery_capsule(self.capsule, self.recovery_code)
        pending = self._pending()
        grant = authorize_readonly_device(
            pending.request, restored.owner_signer, restored.vault_key,
            restored.checkpoint, manually_compared_code=comparison_code(pending.request, now=NOW),
            explicit_approval=True, now=NOW,
        )
        accepted = receive_readonly_device(
            pending, grant, independently_authenticated_owner=restored.owner_public, now=NOW,
        )
        self.assertEqual(accepted.vault_key, restored.vault_key)

    def test_pairing_rejects_schema_duplicates_and_unpinned_owner(self):
        pending = self._pending()
        with self.assertRaises(PairingError):
            comparison_code(b'{"format":1,"format":2}', now=NOW)
        approval = self._approve(pending)
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, approval, independently_authenticated_owner=b"", now=NOW)
        corrupted = json.loads(approval)
        corrupted["grant"]["permission"] = "read_write"
        with self.assertRaises(PairingError):
            receive_readonly_device(pending, json.dumps(corrupted).encode(),
                                    independently_authenticated_owner=self.owner_pub, now=NOW)


if __name__ == "__main__":
    unittest.main()
