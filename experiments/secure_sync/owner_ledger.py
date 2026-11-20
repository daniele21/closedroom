"""Experimental offline owner ledger: SQLite CAS + separate Keychain high-water anchor.

This is a prototype owner for *public* signed device/epoch state only. Secret
epoch keys remain in the macOS Keychain prototype; recording/catalog stores
and installed ClosedRoom are not touched.

SQLite transactions serialize writers using ONE canonical local database path.
Keychain and SQLite cannot commit atomically. A Keychain-held prepared digest
must precede each SQLite update; an interrupted exact signed forward step can
be explicitly completed by the owner, while ambiguity/rollback fails closed.
This does not establish remote freshness or provide a production recovery UI.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from device_pairing import authorize_readonly_device
from vault_keychain import MacKeychainVaultKeys
from vault_manifest import TrustedCheckpoint, public_key_bytes, verify_manifest

FORMAT = "closedroom.offline-owner-ledger"
VERSION = 1
MAX_SIGNED_BYTES = 256 * 1024
MAX_DEVICES = 128
MAX_REQUESTS = 4096
_STATE_FIELDS = {
    "format", "version", "vault_id", "revision", "previous", "owner_public",
    "key_epoch", "key_sha256", "manifest", "devices", "used_request_ids",
}
_RECORD_FIELDS = {"state", "signature"}
_ANCHOR_FIELDS = {"vault_id", "revision", "digest"}


class LedgerError(RuntimeError):
    """An owner-ledger integrity, authorization or crash-safety gate failed."""


def _hex(value: Any, size: int) -> bool:
    return (isinstance(value, str) and len(value) == size
            and all(ch in "0123456789abcdef" for ch in value))


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise LedgerError("Invalid owner ledger encoding") from exc


def _no_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise LedgerError("Duplicate owner ledger field")
        result[key] = value
    return result


def _parse(raw: bytes) -> Any:
    if not isinstance(raw, bytes) or len(raw) > MAX_SIGNED_BYTES:
        raise LedgerError("Owner ledger document exceeds limit")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              LedgerError("Invalid JSON constant")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerError("Invalid owner ledger JSON") from exc


def _cp(raw: Any, vault_id: str) -> TrustedCheckpoint:
    if not isinstance(raw, dict) or set(raw) != {
        "vault_id", "revision", "digest", "key_epoch",
    }:
        raise LedgerError("Invalid manifest checkpoint fields")
    try:
        checkpoint = TrustedCheckpoint(**raw)
    except (TypeError, ValueError) as exc:
        raise LedgerError("Invalid manifest checkpoint") from exc
    if (checkpoint.vault_id != vault_id
            or type(checkpoint.revision) is not int or checkpoint.revision < 0
            or type(checkpoint.key_epoch) is not int or checkpoint.key_epoch < 1
            or not _hex(checkpoint.digest, 64)):
        raise LedgerError("Invalid manifest checkpoint")
    return checkpoint


class OwnerLedger:
    """Local offline experiment; not a production sync/cache persistence owner."""

    def __init__(
        self,
        path: Path,
        vault_id: str,
        authenticated_owner_public: bytes,
        keys: MacKeychainVaultKeys,
    ) -> None:
        if not _hex(vault_id, 32):
            raise LedgerError("Invalid vault identifier")
        if not isinstance(authenticated_owner_public, bytes) or len(authenticated_owner_public) != 32:
            raise LedgerError("Owner key must be authenticated outside storage")
        self.path = Path(path).absolute()
        self.vault_id = vault_id
        self.owner_public = authenticated_owner_public
        self.keys = keys
        if not self.path.parent.is_dir() or self.path.is_symlink():
            raise LedgerError("Missing safe owner ledger directory")
        # Only open a private file. No automatic creation of storage folders.
        if self.path.exists():
            self._check_file()

    def _check_file(self) -> None:
        try:
            item = self.path.lstat()
        except OSError as exc:
            raise LedgerError("Owner ledger cannot be inspected") from exc
        if (not stat.S_ISREG(item.st_mode) or (item.st_mode & 0o077)
                or item.st_uid != os.getuid() or self.path.is_symlink()):
            raise LedgerError("Owner ledger file must be owned, regular and mode 0600")

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
                os.close(fd)
            except FileExistsError:
                pass
            except OSError as exc:
                raise LedgerError("Could not create private owner ledger") from exc
        self._check_file()
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            db.execute(
                "CREATE TABLE IF NOT EXISTS state "
                "(vault_id TEXT PRIMARY KEY, document BLOB NOT NULL)"
            )
            return db
        except BaseException:
            db.close()
            raise

    def _read_anchor(self) -> dict[str, Any] | None:
        text = self.keys.read_ledger_anchor(self.vault_id)
        if text is None:
            return None
        if not isinstance(text, str) or len(text) > 256:
            raise LedgerError("Invalid trusted Keychain anchor")
        try:
            data = _parse(text.encode("ascii"))
        except UnicodeEncodeError as exc:
            raise LedgerError("Invalid trusted Keychain anchor") from exc
        if (not isinstance(data, dict) or set(data) != _ANCHOR_FIELDS
                or data["vault_id"] != self.vault_id
                or type(data["revision"]) is not int or data["revision"] < 0
                or not _hex(data["digest"], 64)):
            raise LedgerError("Corrupt trusted Keychain anchor")
        return data

    def _write_anchor(self, revision: int, digest: str) -> None:
        self.keys.write_ledger_anchor(
            self.vault_id,
            _json({"vault_id": self.vault_id, "revision": revision,
                   "digest": digest}).decode("ascii"),
        )
        if self._read_anchor() != {
            "vault_id": self.vault_id, "revision": revision, "digest": digest,
        }:
            raise LedgerError("Keychain anchor readback mismatch")

    def _validate_state(self, state: Any) -> None:
        if not isinstance(state, dict) or set(state) != _STATE_FIELDS:
            raise LedgerError("Unrecognized owner ledger schema")
        if (state["format"] != FORMAT or type(state["version"]) is not int
                or state["version"] != VERSION or state["vault_id"] != self.vault_id
                or type(state["revision"]) is not int or state["revision"] < 0
                or not _hex(state["key_sha256"], 64)
                or type(state["key_epoch"]) is not int or state["key_epoch"] < 1):
            raise LedgerError("Invalid owner ledger identity/epoch")
        expected = base64.b64encode(self.owner_public).decode("ascii")
        if not isinstance(state["owner_public"], str) or not hmac.compare_digest(
            state["owner_public"], expected,
        ):
            raise LedgerError("Unexpected owner ledger signer")
        if ((state["revision"] == 0 and state["previous"] is not None)
                or (state["revision"] > 0 and not _hex(state["previous"], 64))):
            raise LedgerError("Invalid owner ledger chain")
        checkpoint = _cp(state["manifest"], self.vault_id)
        if checkpoint.key_epoch != state["key_epoch"]:
            raise LedgerError("Ledger epoch disagrees with signed manifest")
        devices = state["devices"]
        used = state["used_request_ids"]
        if not isinstance(devices, dict) or len(devices) > MAX_DEVICES:
            raise LedgerError("Too many registered devices")
        if not isinstance(used, list) or len(used) > MAX_REQUESTS:
            raise LedgerError("Too many used enrollment requests")
        if not all(_hex(x, 32) for x in used) or len(set(used)) != len(used):
            raise LedgerError("Invalid duplicate enrollment nonce")
        for device_id, details in devices.items():
            if (not _hex(device_id, 32) or not isinstance(details, dict)
                    or set(details) != {"status", "epoch"}
                    or details["status"] not in ("active", "needs_repair", "revoked")
                    or type(details["epoch"]) is not int
                    or details["epoch"] < 1
                    or details["epoch"] > state["key_epoch"]):
                raise LedgerError("Invalid registered device")

    def _signed(self, state: dict[str, Any], signer: Ed25519PrivateKey) -> bytes:
        if (not isinstance(signer, Ed25519PrivateKey)
                or not hmac.compare_digest(public_key_bytes(signer), self.owner_public)):
            raise LedgerError("Authenticated owner signing authority required")
        self._validate_state(state)
        body = _json(state)
        signature = signer.sign(body)
        document = _json({
            "state": state, "signature": base64.b64encode(signature).decode("ascii"),
        })
        if len(document) > MAX_SIGNED_BYTES:
            raise LedgerError("Signed ledger exceeds size budget")
        return document

    def _read_prepare(self) -> dict[str, Any] | None:
        """Trusted in-Keychain intent, independent from the mutable SQLite row."""
        raw = self.keys.read_ledger_prepare(self.vault_id)
        if raw is None:
            return None
        if not isinstance(raw, str) or len(raw) > 512:
            raise LedgerError("Corrupt Keychain prepared transition")
        try:
            prepared = _parse(raw.encode("ascii"))
        except UnicodeEncodeError as exc:
            raise LedgerError("Invalid Keychain prepared transition") from exc
        if (not isinstance(prepared, dict)
                or set(prepared) != {"vault_id", "from_revision", "from_digest",
                                    "to_revision", "to_digest"}
                or prepared["vault_id"] != self.vault_id
                or type(prepared["from_revision"]) is not int
                or prepared["from_revision"] < 0
                or type(prepared["to_revision"]) is not int
                or prepared["to_revision"] != prepared["from_revision"] + 1
                or not _hex(prepared["from_digest"], 64)
                or not _hex(prepared["to_digest"], 64)
                or prepared["from_digest"] == prepared["to_digest"]):
            raise LedgerError("Corrupt Keychain prepared transition")
        return prepared

    def _stage_prepare(
        self, from_revision: int, from_digest: str,
        to_revision: int, to_digest: str,
    ) -> None:
        prepared = {
            "vault_id": self.vault_id,
            "from_revision": from_revision, "from_digest": from_digest,
            "to_revision": to_revision, "to_digest": to_digest,
        }
        serialized = _json(prepared).decode("ascii")
        self.keys.write_ledger_prepare(self.vault_id, serialized)
        if self._read_prepare() != prepared:
            raise LedgerError("Prepared transition Keychain readback mismatch")

    def _verified_record(self, db: sqlite3.Connection) -> tuple[dict[str, Any], str]:
        """Verify signature and pinned owner, without trusting SQLite freshness."""
        row = db.execute("SELECT document FROM state WHERE vault_id = ?", (self.vault_id,)).fetchone()
        if row is None:
            raise LedgerError("Missing signed owner ledger: explicit recovery required")
        document = bytes(row[0])
        digest = hashlib.sha256(document).hexdigest()
        record = _parse(document)
        if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
            raise LedgerError("Invalid signed owner ledger document")
        state = record["state"]
        self._validate_state(state)
        try:
            signature = base64.b64decode(record["signature"], validate=True)
            if len(signature) != 64:
                raise ValueError("wrong signature length")
            Ed25519PublicKey.from_public_bytes(self.owner_public).verify(
                signature, _json(state),
            )
        except (ValueError, InvalidSignature, TypeError) as exc:
            raise LedgerError("Owner ledger signature does not verify") from exc
        if not hmac.compare_digest(
            self.keys.load_pinned_owner(self.vault_id), self.owner_public,
        ):
            raise LedgerError("Trusted owner pin mismatch")
        return state, digest

    def _checked(self, db: sqlite3.Connection) -> tuple[dict[str, Any], str]:
        state, digest = self._verified_record(db)
        anchor = self._read_anchor()
        if anchor is None:
            raise LedgerError("Missing ledger or trusted anchor: explicit recovery required")
        if anchor != {
            "vault_id": self.vault_id, "revision": state["revision"],
            "digest": digest,
        }:
            raise LedgerError("SQLite/Keychain high-water mismatch: frozen until recovery")
        # A prepared write may have stopped before SQLite COMMIT, after COMMIT,
        # or during Keychain acknowledgement. Even a DB equal to the old anchor
        # is ambiguous: it may have been rolled back after a real commit.
        if self._read_prepare() is not None:
            raise LedgerError("Unresolved Keychain prepared transition: explicit recovery required")
        return state, digest

    def recover_prepared_transition(
        self, owner_signer: Ed25519PrivateKey, *,
        expected_new_digest: str, explicit_confirmation: bool,
    ) -> str:
        """Explicit local forward repair, NEVER trust or roll back SQLite alone.

        A prepared transition written to Keychain *before* SQLite COMMIT binds
        the old high-water anchor to the exact signed successor document.
        The operator must independently confirm which candidate was intended.
        No prepared record => no repair. A DB still at the old anchor could be
        either uncommitted OR a malicious post-commit rollback: refuse both.
        """
        if (type(explicit_confirmation) is not bool or not explicit_confirmation
                or not _hex(expected_new_digest, 64)
                or not isinstance(owner_signer, Ed25519PrivateKey)
                or not hmac.compare_digest(
                    public_key_bytes(owner_signer), self.owner_public,
                )):
            raise LedgerError("Explicit authenticated owner recovery required")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            state, digest = self._verified_record(db)
            anchor = self._read_anchor()
            prepared = self._read_prepare()
            if anchor is None or prepared is None:
                raise LedgerError("No independently Keychain-prepared transition")
            if not hmac.compare_digest(prepared["to_digest"], expected_new_digest):
                raise LedgerError("Wrong independently confirmed successor digest")
            before = {
                "vault_id": self.vault_id,
                "revision": prepared["from_revision"],
                "digest": prepared["from_digest"],
            }
            after = {
                "vault_id": self.vault_id,
                "revision": prepared["to_revision"],
                "digest": prepared["to_digest"],
            }
            if not (state["revision"] == after["revision"]
                    and hmac.compare_digest(digest, after["digest"])
                    and state["previous"] == before["digest"]):
                raise LedgerError("Prepared successor unavailable or rolled back: recovery refused")
            # Detect missing, changed or unrelated secrets before asserting the
            # new epoch. The Keychain is the separate trust/secret owner.
            key = self.keys.load_epoch_key(self.vault_id, state["key_epoch"])
            if not hmac.compare_digest(
                hashlib.sha256(key).hexdigest(), state["key_sha256"],
            ):
                raise LedgerError("Trusted epoch key does not match signed successor")
            if anchor == before:
                self._write_anchor(after["revision"], after["digest"])
            elif anchor != after:
                raise LedgerError("Keychain high-water is not a prepared predecessor/successor")
            # If clearing the pending mark fails, all future ordinary reads
            # remain frozen until a subsequent explicit recovery invocation.
            self.keys.clear_ledger_prepare(self.vault_id)
            if self._read_prepare() is not None:
                raise LedgerError("Keychain preparation cleanup failed")
            db.commit()
            return "recovered"
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def bootstrap(self, owner_signer: Ed25519PrivateKey, signed_genesis: bytes) -> None:
        """Initialize from a locally authenticated signed genesis only once."""
        if not isinstance(owner_signer, Ed25519PrivateKey) or not hmac.compare_digest(
            public_key_bytes(owner_signer), self.owner_public,
        ):
            raise LedgerError("Authenticated owner required for bootstrap")
        genesis = verify_manifest(signed_genesis, self.owner_public)
        if (genesis.vault_id != self.vault_id or genesis.revision != 0
                or genesis.key_epoch != 1):
            raise LedgerError("Invalid initial manifest")
        # Only the previously created local Keychain master secret can initialize.
        key = self.keys.load_epoch_key(self.vault_id, 1)
        self.keys.pin_authenticated_owner(self.vault_id, self.owner_public)
        state = {
            "format": FORMAT, "version": VERSION, "vault_id": self.vault_id,
            "revision": 0, "previous": None,
            "owner_public": base64.b64encode(self.owner_public).decode("ascii"),
            "key_epoch": 1, "key_sha256": hashlib.sha256(key).hexdigest(),
            "manifest": asdict(genesis), "devices": {}, "used_request_ids": [],
        }
        document = self._signed(state, owner_signer)
        digest = hashlib.sha256(document).hexdigest()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            if (db.execute("SELECT 1 FROM state WHERE vault_id = ?",
                           (self.vault_id,)).fetchone() or self._read_anchor() is not None):
                raise LedgerError("Ledger is already initialized or ambiguous")
            db.execute("INSERT INTO state (vault_id, document) VALUES (?, ?)",
                       (self.vault_id, document))
            db.commit()
            self._write_anchor(0, digest)
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def read(self) -> dict[str, Any]:
        """Authenticate all state against owner's pin and separate Keychain anchor."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            state, _ = self._checked(db)
            db.commit()
            return state
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def _persist(
        self, db: sqlite3.Connection, old: dict[str, Any],
        old_digest: str, new: dict[str, Any],
        signer: Ed25519PrivateKey,
    ) -> None:
        if not db.in_transaction:
            raise LedgerError("Ledger must be locked before advancing")
        new["revision"] = old["revision"] + 1
        new["previous"] = old_digest
        doc = self._signed(new, signer)
        digest = hashlib.sha256(doc).hexdigest()
        # The independent Keychain preparation MUST precede SQLite COMMIT.
        # On a crash, only this exact signed successor is eligible for explicit
        # forward recovery. A rolled-back DB or missing intent remains blocked.
        self._stage_prepare(old["revision"], old_digest, new["revision"], digest)
        result = db.execute(
            "UPDATE state SET document = ? WHERE vault_id = ? AND document = ?",
            (doc, self.vault_id, db.execute(
                "SELECT document FROM state WHERE vault_id = ?", (self.vault_id,),
            ).fetchone()[0]),
        )
        if result.rowcount != 1:
            raise LedgerError("Concurrent owner ledger update refused")
        db.commit()
        self._write_anchor(new["revision"], digest)
        # A failure here leaves the ledger frozen despite anchor == SQLite,
        # until the owner explicitly proves and finishes the preparation.
        self.keys.clear_ledger_prepare(self.vault_id)
        if self._read_prepare() is not None:
            raise LedgerError("Unresolved Keychain prepared transition")

    def authorize_and_record(
        self,
        request: bytes,
        signer: Ed25519PrivateKey,
        *,
        manually_compared_code: str,
        explicit_approval: bool,
        now: int | None = None,
    ) -> bytes:
        """Issue one read-only grant and durably consume request before return."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old, digest = self._checked(db)
            if len(old["used_request_ids"]) >= MAX_REQUESTS or len(old["devices"]) >= MAX_DEVICES:
                raise LedgerError("Owner device/nonce registry capacity reached")
            checkpoint = _cp(old["manifest"], self.vault_id)
            key = self.keys.load_epoch_key(self.vault_id, old["key_epoch"])
            if hashlib.sha256(key).hexdigest() != old["key_sha256"]:
                raise LedgerError("Local epoch key does not match trusted state")
            # The signing/approval owner is the canonical pairing proof.
            grant = authorize_readonly_device(
                request, signer, key, checkpoint,
                manually_compared_code=manually_compared_code,
                explicit_approval=explicit_approval, now=now,
            )
            doc = _parse(grant)
            item = doc["grant"]
            if item["vault_id"] != self.vault_id:
                raise LedgerError("Attempted enrollment into another vault")
            request_id, device_id = item["request_id"], item["device_id"]
            if not _hex(request_id, 32) or not _hex(device_id, 32):
                raise LedgerError("Invalid enrollment identifiers")
            if request_id in old["used_request_ids"] or device_id in old["devices"]:
                raise LedgerError("Repeated enrollment request or device")
            new = json.loads(_json(old))
            new["used_request_ids"].append(request_id)
            new["devices"][device_id] = {"status": "active", "epoch": old["key_epoch"]}
            self._persist(db, old, digest, new, signer)
            return grant
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def revoke_and_rotate(
        self, device_id: str, signer: Ed25519PrivateKey,
        next_signed_manifest: bytes,
    ) -> bytes:
        """Revoke and create a NEW independent epoch key in Keychain first.

        Remaining devices require explicit fresh grants for the new epoch.
        This does not remotely erase their previously decrypted ciphertext.
        Returns the fresh key to the local owner only after ledger+anchor proof.
        """
        if not _hex(device_id, 32):
            raise LedgerError("Invalid revoked device identity")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old, digest = self._checked(db)
            entry = old["devices"].get(device_id)
            if entry is None or entry["status"] == "revoked":
                raise LedgerError("Device is not currently enrolled")
            current = _cp(old["manifest"], self.vault_id)
            advanced = verify_manifest(
                next_signed_manifest, self.owner_public, current,
            )
            if (advanced.revision != current.revision + 1
                    or advanced.key_epoch != current.key_epoch + 1):
                raise LedgerError("Revocation requires a signed new manifest epoch")
            # Keychain write precedes owner-ledger commit; an unexpected crash
            # can strand an unused epoch secret but must not lose the new epoch.
            fresh = secrets.token_bytes(32)
            self.keys.create_epoch_key(self.vault_id, advanced.key_epoch, fresh)
            new = json.loads(_json(old))
            new["key_epoch"] = advanced.key_epoch
            new["key_sha256"] = hashlib.sha256(fresh).hexdigest()
            new["manifest"] = asdict(advanced)
            for ident, details in new["devices"].items():
                if ident == device_id:
                    details["status"] = "revoked"
                elif details["status"] == "active":
                    details["status"] = "needs_repair"
            self._persist(db, old, digest, new, signer)
            return fresh
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()
