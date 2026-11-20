"""Adversarial offline durability/rotation tests, synthetic secrets only.

A fake Keychain permits deterministic crash tests. It does not qualify
packaged-app Keychain, secure user recovery or a physical second Mac.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from device_pairing import (
    PairingError, comparison_code, create_device_request, receive_readonly_device,
)
from owner_ledger import LedgerError, OwnerLedger
from secure_sync import SecureSyncError, open_snapshot, seal_snapshot, transcript_snapshot
from vault_keychain import KeychainError, MacKeychainVaultKeys, SERVICE
from vault_manifest import (
    new_manifest, new_vault_id, object_reference, public_key_bytes, sign_manifest,
    verify_manifest,
)

NOW = 1795000000


class FakeKeychain:
    def __init__(self):
        self.data = {}
        self.fail_anchor = False
        self.fail_epoch = False

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, value):
        if self.fail_anchor and username.endswith(":ledger-anchor"):
            raise OSError("Synthetic Keychain anchor outage")
        if self.fail_epoch and ":epoch:" in username:
            raise OSError("Synthetic Keychain epoch storage outage")
        self.data[(service, username)] = value


class OfflineLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "owner.db"
        self.backend = FakeKeychain()
        self.keys = MacKeychainVaultKeys(_test_backend=self.backend)
        self.vault = new_vault_id()
        self.master = self.keys.create(self.vault)
        self.signer = self.keys.create_owner_signer(self.vault)
        self.pub = public_key_bytes(self.signer)
        self.genesis = sign_manifest(
            new_manifest(vault_id=self.vault, revision=0, previous=None),
            self.signer,
        )
        self.cp = verify_manifest(self.genesis, self.pub)
        self.ledger = OwnerLedger(self.path, self.vault, self.pub, self.keys)
        self.ledger.bootstrap(self.signer, self.genesis)

    def _new_ledger(self):
        # Separate process-like object, same disk and Keychain backend.
        return OwnerLedger(
            self.path, self.vault, self.pub,
            MacKeychainVaultKeys(_test_backend=self.backend),
        )

    def _approve(self, pending=None):
        pending = pending or create_device_request(self.vault, now=NOW)
        grant = self.ledger.authorize_and_record(
            pending.request, self.signer,
            manually_compared_code=comparison_code(pending.request, now=NOW),
            explicit_approval=True, now=NOW,
        )
        return pending, grant

    def _advance(self):
        return sign_manifest(new_manifest(
            vault_id=self.vault, revision=self.cp.revision + 1,
            previous=self.cp.digest, key_epoch=self.cp.key_epoch + 1,
        ), self.signer)

    def test_bootstrap_persists_only_public_signed_state_with_private_mode(self):
        state = self._new_ledger().read()
        self.assertEqual(state["revision"], 0)
        self.assertEqual(state["key_epoch"], 1)
        self.assertEqual(state["devices"], {})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        raw = self.path.read_bytes()
        self.assertNotIn(self.master, raw)
        self.assertNotIn(self.signer.private_bytes_raw(), raw)

    def test_replay_rejected_across_owner_restarts(self):
        pending, grant = self._approve()
        state = self._new_ledger().read()
        self.assertIn(json.loads(pending.request)["request_id"], state["used_request_ids"])
        self.assertEqual(state["revision"], 1)
        with self.assertRaises(LedgerError):
            self._new_ledger().authorize_and_record(
                pending.request, self.signer,
                manually_compared_code=comparison_code(pending.request, now=NOW),
                explicit_approval=True, now=NOW,
            )
        self.assertEqual(self._new_ledger().read()["revision"], 1)
        accepted = receive_readonly_device(
            pending, grant, independently_authenticated_owner=self.pub, now=NOW,
        )
        self.assertEqual(accepted.vault_key, self.master)

    def test_duplicate_concurrent_style_instances_do_not_reissue(self):
        left, right = self._new_ledger(), self._new_ledger()
        pending = create_device_request(self.vault, now=NOW)
        code = comparison_code(pending.request, now=NOW)
        left.authorize_and_record(
            pending.request, self.signer, manually_compared_code=code,
            explicit_approval=True, now=NOW,
        )
        with self.assertRaises(LedgerError):
            right.authorize_and_record(
                pending.request, self.signer, manually_compared_code=code,
                explicit_approval=True, now=NOW,
            )

    def test_no_permission_from_human_bypass_or_ownering_impersonator(self):
        pending = create_device_request(self.vault, now=NOW)
        for permitted, code in ((False, comparison_code(pending.request, now=NOW)), (True, "00000000")):
            with self.assertRaises(PairingError):
                self.ledger.authorize_and_record(
                    pending.request, self.signer, manually_compared_code=code,
                    explicit_approval=permitted, now=NOW,
                )
        self.assertEqual(self.ledger.read()["revision"], 0)
        # Missing or changed pinned identity blocks all operations.
        self.backend.data[(SERVICE, self.vault + ":owner-pin")] = base64.b64encode(b"x" * 32).decode()
        with self.assertRaises(LedgerError):
            self.ledger.read()

    def test_keychain_anchor_stops_signed_database_rollback(self):
        with sqlite3.connect(self.path) as db:
            previous = db.execute(
                "SELECT document FROM state WHERE vault_id=?", (self.vault,),
            ).fetchone()[0]
        self._approve()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE state SET document = ? WHERE vault_id=?",
                       (previous, self.vault))
        with self.assertRaisesRegex(LedgerError, "high-water mismatch"):
            self._new_ledger().read()

    def test_external_database_tampering_fails_even_with_anchor(self):
        self._approve()
        with sqlite3.connect(self.path) as db:
            document = json.loads(db.execute(
                "SELECT document FROM state WHERE vault_id=?", (self.vault,),
            ).fetchone()[0])
            document["state"]["devices"]["f" * 32] = {"status": "active", "epoch": 1}
            db.execute("UPDATE state SET document=? WHERE vault_id=?",
                       (json.dumps(document).encode(), self.vault))
        with self.assertRaises(LedgerError):
            self._new_ledger().read()

    def test_missing_anchor_is_never_silently_recreated(self):
        self.backend.data.pop((SERVICE, self.vault + ":ledger-anchor"))
        with self.assertRaisesRegex(LedgerError, "Missing ledger or trusted anchor"):
            self._new_ledger().read()
        with self.assertRaises(LedgerError):
            self._new_ledger().bootstrap(self.signer, self.genesis)

    def test_keychain_failure_after_sqlite_commit_freezes_ledger(self):
        self.backend.fail_anchor = True
        pending = create_device_request(self.vault, now=NOW)
        with self.assertRaises(KeychainError):
            self.ledger.authorize_and_record(
                pending.request, self.signer,
                manually_compared_code=comparison_code(pending.request, now=NOW),
                explicit_approval=True, now=NOW,
            )
        self.backend.fail_anchor = False
        with self.assertRaisesRegex(LedgerError, "high-water mismatch"):
            self._new_ledger().read()
        # No automatic repair from the later SQLite state.
        with self.assertRaises(LedgerError):
            self._new_ledger().authorize_and_record(
                pending.request, self.signer,
                manually_compared_code=comparison_code(pending.request, now=NOW),
                explicit_approval=True, now=NOW,
            )

    def test_keychain_failure_before_epoch_commit_keeps_prior_state(self):
        pending, _ = self._approve()
        self.backend.fail_epoch = True
        with self.assertRaises(KeychainError):
            self.ledger.revoke_and_rotate(
                json.loads(pending.request)["device_id"], self.signer, self._advance(),
            )
        self.backend.fail_epoch = False
        state = self._new_ledger().read()
        self.assertEqual(state["key_epoch"], 1)
        self.assertEqual(state["devices"][json.loads(pending.request)["device_id"]]["status"], "active")

    def test_revocation_rotates_to_independent_key_and_signed_epoch(self):
        removed, removed_grant = self._approve()
        survivor, survivor_grant = self._approve()
        revoked_id = json.loads(removed.request)["device_id"]
        surviving_id = json.loads(survivor.request)["device_id"]
        old_recipient = receive_readonly_device(
            removed, removed_grant, independently_authenticated_owner=self.pub, now=NOW,
        )
        new_key = self.ledger.revoke_and_rotate(revoked_id, self.signer, self._advance())
        new_state = self._new_ledger().read()
        self.assertEqual(new_state["key_epoch"], 2)
        self.assertEqual(new_state["devices"][revoked_id]["status"], "revoked")
        self.assertEqual(new_state["devices"][surviving_id]["status"], "needs_repair")
        self.assertNotEqual(new_key, self.master)
        self.assertEqual(self.keys.load_epoch_key(self.vault, 2), new_key)
        future_snapshot = transcript_snapshot({"id": "post-revocation", "text": "future content"})
        blob = seal_snapshot(future_snapshot, new_key)
        self.assertEqual(open_snapshot(blob, new_key), future_snapshot)
        with self.assertRaises(SecureSyncError):
            open_snapshot(blob, old_recipient.vault_key)
        # The pre-rotation grant is now below an authenticated epoch checkpoint.
        next_cp = verify_manifest(self._advance(), self.pub, self.cp)
        with self.assertRaises(PairingError):
            receive_readonly_device(
                survivor, survivor_grant, independently_authenticated_owner=self.pub,
                minimum_checkpoint=next_cp, now=NOW,
            )

    def test_post_rotation_new_pairing_uses_fresh_epoch_not_previous(self):
        revoked, _ = self._approve()
        self.ledger.revoke_and_rotate(
            json.loads(revoked.request)["device_id"], self.signer, self._advance(),
        )
        pending, grant = self._approve()
        restored = receive_readonly_device(
            pending, grant, independently_authenticated_owner=self.pub, now=NOW,
        )
        self.assertEqual(restored.checkpoint.key_epoch, 2)
        self.assertEqual(restored.vault_key, self.keys.load_epoch_key(self.vault, 2))
        self.assertNotEqual(restored.vault_key, self.master)

    def test_unsigned_or_skipped_manifest_epoch_cannot_revoke(self):
        pending, _ = self._approve()
        ident = json.loads(pending.request)["device_id"]
        bad = sign_manifest(new_manifest(
            vault_id=self.vault, revision=1, previous=self.cp.digest, key_epoch=1,
        ), self.signer)
        with self.assertRaises(LedgerError):
            self.ledger.revoke_and_rotate(ident, self.signer, bad)
        with self.assertRaises(LedgerError):
            self.ledger.revoke_and_rotate("f" * 32, self.signer, self._advance())
        self.assertEqual(self.ledger.read()["key_epoch"], 1)

    def test_duplicate_revoke_does_not_rotate_again(self):
        pending, _ = self._approve()
        ident = json.loads(pending.request)["device_id"]
        self.ledger.revoke_and_rotate(ident, self.signer, self._advance())
        with self.assertRaises(LedgerError):
            self._new_ledger().revoke_and_rotate(ident, self.signer, self._advance())
        self.assertEqual(self._new_ledger().read()["key_epoch"], 2)

    def test_permissions_and_symlink_are_not_accepted(self):
        os.chmod(self.path, 0o644)
        with self.assertRaises(LedgerError):
            self._new_ledger()
        os.chmod(self.path, 0o600)
        link = Path(self.tmp.name) / "owner-link.db"
        link.symlink_to(self.path)
        with self.assertRaises(LedgerError):
            OwnerLedger(link, self.vault, self.pub, self.keys)


    def _document_digest(self):
        import hashlib
        with sqlite3.connect(self.path) as db:
            document = db.execute(
                "SELECT document FROM state WHERE vault_id=?", (self.vault,),
            ).fetchone()[0]
        return hashlib.sha256(document).hexdigest()

    def _interrupt_after_sql_commit(self):
        self.backend.fail_anchor = True
        pending = create_device_request(self.vault, now=NOW)
        try:
            with self.assertRaises(KeychainError):
                self.ledger.authorize_and_record(
                    pending.request, self.signer,
                    manually_compared_code=comparison_code(pending.request, now=NOW),
                    explicit_approval=True, now=NOW,
                )
        finally:
            self.backend.fail_anchor = False
        return pending, self._document_digest()

    def test_exact_prepared_forward_step_recovers_only_with_owner_confirmation(self):
        pending, successor_digest = self._interrupt_after_sql_commit()
        self.assertIsNotNone(self.keys.read_ledger_prepare(self.vault))
        with self.assertRaises(LedgerError):
            self._new_ledger().read()
        self.assertEqual(self._new_ledger().recover_prepared_transition(
            self.signer, expected_new_digest=successor_digest,
            explicit_confirmation=True,
        ), "recovered")
        self.assertIsNone(self.keys.read_ledger_prepare(self.vault))
        state = self._new_ledger().read()
        self.assertEqual(state["revision"], 1)
        self.assertIn(json.loads(pending.request)["request_id"], state["used_request_ids"])
        with self.assertRaises(LedgerError):
            self._new_ledger().authorize_and_record(
                pending.request, self.signer,
                manually_compared_code=comparison_code(pending.request, now=NOW),
                explicit_approval=True, now=NOW,
            )
        self.assertEqual(self._new_ledger().read()["revision"], 1)

    def test_recovery_refuses_wrong_digest_absent_consent_and_wrong_signer(self):
        from vault_manifest import generate_owner_signing_key
        _, digest = self._interrupt_after_sql_commit()
        for signer, expected, consent in (
            (self.signer, digest, False),
            (self.signer, "a" * 64, True),
            (generate_owner_signing_key(), digest, True),
        ):
            with self.subTest(consent=consent, expected=expected), self.assertRaises(LedgerError):
                self._new_ledger().recover_prepared_transition(
                    signer, expected_new_digest=expected,
                    explicit_confirmation=consent,
                )
        with self.assertRaises(LedgerError):
            self._new_ledger().read()

    def test_recovery_refuses_if_keychain_preparation_is_missing(self):
        _, digest = self._interrupt_after_sql_commit()
        self.backend.data.pop((SERVICE, self.vault + ":ledger-prepare"))
        with self.assertRaisesRegex(LedgerError, "No independently Keychain-prepared"):
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest=digest,
                explicit_confirmation=True,
            )
        with self.assertRaises(LedgerError):
            self._new_ledger().read()

    def test_recovery_does_not_accept_rolled_back_old_database(self):
        with sqlite3.connect(self.path) as db:
            old_document = db.execute(
                "SELECT document FROM state WHERE vault_id=?", (self.vault,),
            ).fetchone()[0]
        _, digest = self._interrupt_after_sql_commit()
        # DB may have committed and THEN been restored from backup. As long
        # as Keychain preparation remains, old == anchor cannot be assumed safe.
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE state SET document=? WHERE vault_id=?",
                       (old_document, self.vault))
        with self.assertRaisesRegex(LedgerError, "Unresolved Keychain prepared"):
            self._new_ledger().read()
        with self.assertRaisesRegex(LedgerError, "rolled back"):
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest=digest,
                explicit_confirmation=True,
            )

    def test_recovery_refuses_prepared_but_uncommitted_sqlite_state(self):
        old_digest = self._document_digest()
        self.ledger._stage_prepare(0, old_digest, 1, "b" * 64)
        with self.assertRaises(LedgerError):
            self._new_ledger().read()
        with self.assertRaisesRegex(LedgerError, "rolled back"):
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest="b" * 64,
                explicit_confirmation=True,
            )

    def test_recovery_refuses_signed_alternate_successor_document(self):
        _, digest = self._interrupt_after_sql_commit()
        with sqlite3.connect(self.path) as db:
            document = json.loads(db.execute(
                "SELECT document FROM state WHERE vault_id=?", (self.vault,),
            ).fetchone()[0])
            state = document["state"]
            state["devices"]["c" * 32] = {"status": "active", "epoch": 1}
            forged_signed = self.ledger._signed(state, self.signer)
            db.execute("UPDATE state SET document=? WHERE vault_id=?",
                       (forged_signed, self.vault))
        with self.assertRaisesRegex(LedgerError, "rolled back"):
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest=digest,
                explicit_confirmation=True,
            )

    def test_recovery_refuses_wrong_or_missing_epoch_secret(self):
        _, digest = self._interrupt_after_sql_commit()
        self.backend.data[(SERVICE, self.vault + ":master")] = base64.b64encode(
            b"z" * 32,
        ).decode()
        with self.assertRaisesRegex(LedgerError, "epoch key"):
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest=digest,
                explicit_confirmation=True,
            )
        with self.assertRaises(LedgerError):
            self._new_ledger().read()

    def test_missing_preparation_cannot_invoke_recovery_on_healthy_ledger(self):
        with self.assertRaisesRegex(LedgerError, "No independently Keychain-prepared"):
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest="d" * 64,
                explicit_confirmation=True,
            )
        self.assertEqual(self.ledger.read()["revision"], 0)

    def test_corrupt_preparation_is_not_ignored_or_repaired(self):
        self.backend.data[(SERVICE, self.vault + ":ledger-prepare")] = '{"from_revision":0}'
        with self.assertRaisesRegex(LedgerError, "Corrupt Keychain prepared"):
            self._new_ledger().read()
        with self.assertRaises(LedgerError):
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest="e" * 64,
                explicit_confirmation=True,
            )

    def test_epoch_rotation_split_commit_can_recover_with_independent_secret(self):
        pending, _ = self._approve()
        self.backend.fail_anchor = True
        try:
            with self.assertRaises(KeychainError):
                self.ledger.revoke_and_rotate(
                    json.loads(pending.request)["device_id"],
                    self.signer, self._advance(),
                )
        finally:
            self.backend.fail_anchor = False
        digest = self._document_digest()
        with self.assertRaises(LedgerError):
            self._new_ledger().read()
        self.assertEqual(
            self._new_ledger().recover_prepared_transition(
                self.signer, expected_new_digest=digest,
                explicit_confirmation=True,
            ), "recovered",
        )
        self.assertEqual(self._new_ledger().read()["key_epoch"], 2)
        self.assertEqual(
            self._new_ledger().read()["devices"][json.loads(pending.request)["device_id"]]["status"],
            "revoked",
        )
        self.assertNotEqual(self.keys.load_epoch_key(self.vault, 2), self.master)

    def test_failed_cleanup_after_anchor_acceptance_requires_explicit_completion(self):
        pending = create_device_request(self.vault, now=NOW)
        original_clear = self.keys.clear_ledger_prepare
        def fail_clear(vault_id):
            raise KeychainError("Synthetic post-anchor cleanup failed")
        self.keys.clear_ledger_prepare = fail_clear
        try:
            with self.assertRaises(KeychainError):
                self.ledger.authorize_and_record(
                    pending.request, self.signer,
                    manually_compared_code=comparison_code(pending.request, now=NOW),
                    explicit_approval=True, now=NOW,
                )
        finally:
            self.keys.clear_ledger_prepare = original_clear
        digest = self._document_digest()
        with self.assertRaisesRegex(LedgerError, "Unresolved Keychain prepared"):
            self._new_ledger().read()
        self.assertEqual(self._new_ledger().recover_prepared_transition(
            self.signer, expected_new_digest=digest,
            explicit_confirmation=True,
        ), "recovered")
        self.assertEqual(self._new_ledger().read()["revision"], 1)

    def test_prepared_transition_write_failure_before_commit_keeps_old_record(self):
        old_digest = self._document_digest()
        original = self.keys.write_ledger_prepare
        def fail_prepare(vault_id, serialized):
            raise KeychainError("Synthetic prepare write failure")
        self.keys.write_ledger_prepare = fail_prepare
        try:
            pending = create_device_request(self.vault, now=NOW)
            with self.assertRaises(KeychainError):
                self.ledger.authorize_and_record(
                    pending.request, self.signer,
                    manually_compared_code=comparison_code(pending.request, now=NOW),
                    explicit_approval=True, now=NOW,
                )
        finally:
            self.keys.write_ledger_prepare = original
        self.assertEqual(self._document_digest(), old_digest)
        self.assertEqual(self._new_ledger().read()["revision"], 0)


if __name__ == "__main__":
    unittest.main()
