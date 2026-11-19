"""Offline authenticated vault-manifest proof; never reads or writes a network endpoint.

The owner public key MUST be authenticated outside storage (pairing/recovery).
An independent trusted checkpoint detects rollbacks only after the client has
previously seen a newer head. A fresh device cannot establish freshness from
untrusted Drive data alone.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

FORMAT = "closedroom.vault-manifest"
VERSION = 1
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_OBJECTS = 2048
_HEADER_FIELDS = frozenset({"format", "version", "vault_id", "revision", "previous", "key_epoch", "objects"})
_DOCUMENT_FIELDS = frozenset({"manifest", "signature"})
_OBJECT_FIELDS = frozenset({"id", "sha256"})


class ManifestError(ValueError):
    """Invalid, untrusted, replayed, or conflicting signed vault state."""


@dataclass(frozen=True)
class TrustedCheckpoint:
    """Private and durable, never obtained from the same untrusted Drive head."""

    vault_id: str
    revision: int
    digest: str
    key_epoch: int


def generate_owner_signing_key() -> Ed25519PrivateKey:
    """Caller must keep the private key out of Drive, logs and snapshots."""
    return Ed25519PrivateKey.generate()


def public_key_bytes(signing_key: Ed25519PrivateKey) -> bytes:
    return signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def new_vault_id() -> str:
    return secrets.token_hex(16)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ManifestError("Invalid manifest encoding") from exc


def _reject_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in items:
        if key in obj:
            raise ManifestError("Duplicate manifest field")
        obj[key] = value
    return obj


def _hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(x in "0123456789abcdef" for x in value)


def _validate(manifest: Any) -> None:
    if not isinstance(manifest, dict) or set(manifest) != _HEADER_FIELDS:
        raise ManifestError("Invalid manifest schema")
    if manifest["format"] != FORMAT or type(manifest["version"]) is not int or manifest["version"] != VERSION:
        raise ManifestError("Unsupported manifest version")
    if not _hex(manifest["vault_id"], 32):
        raise ManifestError("Invalid vault id")
    revision = manifest["revision"]
    epoch = manifest["key_epoch"]
    if type(revision) is not int or revision < 0 or type(epoch) is not int or epoch < 1:
        raise ManifestError("Invalid revision or key epoch")
    if (revision == 0 and manifest["previous"] is not None) or (revision > 0 and not _hex(manifest["previous"], 64)):
        raise ManifestError("Invalid manifest chain pointer")
    objects = manifest["objects"]
    if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ManifestError("Invalid object list")
    seen = set()
    for item in objects:
        if not isinstance(item, dict) or set(item) != _OBJECT_FIELDS:
            raise ManifestError("Invalid object reference")
        if not _hex(item["id"], 32) or not _hex(item["sha256"], 64) or item["id"] in seen:
            raise ManifestError("Invalid or duplicate object reference")
        seen.add(item["id"])


def new_manifest(*, vault_id: str, revision: int, previous: str | None,
                 key_epoch: int = 1, objects: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Construct explicit, versioned content; no filesystem or network I/O."""
    manifest = {
        "format": FORMAT, "version": VERSION, "vault_id": vault_id,
        "revision": revision, "previous": previous, "key_epoch": key_epoch,
        "objects": list(objects or []),
    }
    _validate(manifest)
    return manifest


def sign_manifest(manifest: Mapping[str, Any], owner_signing_key: Ed25519PrivateKey) -> bytes:
    """Canonical Ed25519 signature; caller must enforce authorization to sign."""
    if not isinstance(owner_signing_key, Ed25519PrivateKey):
        raise ManifestError("Owner signing key required")
    data = dict(manifest)
    _validate(data)
    payload = _canonical(data)
    if len(payload) > MAX_DOCUMENT_BYTES - 300:
        raise ManifestError("Manifest too large")
    signature = owner_signing_key.sign(payload)
    document = _canonical({"manifest": data, "signature": base64.b64encode(signature).decode("ascii")})
    if len(document) > MAX_DOCUMENT_BYTES:
        raise ManifestError("Signed manifest too large")
    return document


def verify_manifest(document: bytes, pinned_owner_public_key: bytes,
                    checkpoint: TrustedCheckpoint | None = None) -> TrustedCheckpoint:
    """Check signature, structure, and contiguous advancement from trusted state.

    Same exact signed head is an idempotent no-op; an older head, alternate
    same-revision head, skipped revision or changed epoch without a chain is
    rejected. No provider-freshness claim on first-ever enrollment.
    """
    if not isinstance(document, bytes) or len(document) > MAX_DOCUMENT_BYTES:
        raise ManifestError("Invalid manifest document size")
    if not isinstance(pinned_owner_public_key, bytes) or len(pinned_owner_public_key) != 32:
        raise ManifestError("Authenticated owner public key required")
    try:
        raw = json.loads(document.decode("utf-8"), object_pairs_hook=_reject_duplicates,
                         parse_constant=lambda _: (_ for _ in ()).throw(ManifestError("Invalid JSON constant")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("Invalid manifest document") from exc
    if not isinstance(raw, dict) or set(raw) != _DOCUMENT_FIELDS:
        raise ManifestError("Invalid signed manifest envelope")
    manifest = raw["manifest"]
    _validate(manifest)
    signature_b64 = raw["signature"]
    if not isinstance(signature_b64, str):
        raise ManifestError("Invalid manifest signature")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ManifestError("Invalid manifest signature") from exc
    if len(signature) != 64:
        raise ManifestError("Invalid manifest signature length")
    try:
        Ed25519PublicKey.from_public_bytes(pinned_owner_public_key).verify(signature, _canonical(manifest))
    except (InvalidSignature, ValueError) as exc:
        raise ManifestError("Manifest signature verification failed") from exc
    digest = hashlib.sha256(_canonical(manifest)).hexdigest()
    proposed = TrustedCheckpoint(manifest["vault_id"], manifest["revision"], digest, manifest["key_epoch"])
    if checkpoint is None:
        if proposed.revision != 0 or manifest["previous"] is not None:
            raise ManifestError("Genesis trust anchor required before later manifests")
        return proposed
    if checkpoint.vault_id != proposed.vault_id:
        raise ManifestError("Wrong vault")
    if checkpoint == proposed:
        return checkpoint
    if proposed.revision != checkpoint.revision + 1 or manifest["previous"] != checkpoint.digest:
        raise ManifestError("Rollback, skipped revision or forked chain")
    if proposed.key_epoch < checkpoint.key_epoch or proposed.key_epoch > checkpoint.key_epoch + 1:
        raise ManifestError("Invalid key rotation sequence")
    return proposed


def object_reference(object_id: str, encrypted_blob: bytes) -> dict[str, str]:
    """The blob must already be encrypted and authenticated by the snapshot owner."""
    if not _hex(object_id, 32) or not isinstance(encrypted_blob, bytes):
        raise ManifestError("Invalid encrypted object identity or bytes")
    return {"id": object_id, "sha256": hashlib.sha256(encrypted_blob).hexdigest()}


def verify_object(reference: Mapping[str, Any], encrypted_blob: bytes) -> None:
    """Detect cloud blob substitution before decrypting in the snapshot owner."""
    if not isinstance(reference, Mapping) or set(reference) != _OBJECT_FIELDS or not _hex(reference["id"], 32) or not _hex(reference["sha256"], 64):
        raise ManifestError("Invalid encrypted object reference")
    if not isinstance(encrypted_blob, bytes) or hashlib.sha256(encrypted_blob).hexdigest() != reference["sha256"]:
        raise ManifestError("Encrypted object hash mismatch")
