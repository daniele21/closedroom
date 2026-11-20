"""Offline, versioned recovery capsule for the experimental ClosedRoom vault.

This protocol is deliberately separate from app storage and Drive transport.
A 256-bit, randomly generated recovery code must be held independently from
the encrypted capsule. No password-derived/low-entropy secrets are supported.
A recovered trusted checkpoint is only as fresh as the capsule the user has;
a compromised provider can replay an older authenticated capsule.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from vault_manifest import TrustedCheckpoint, public_key_bytes

FORMAT = "closedroom.recovery-capsule"
VERSION = 1
MAX_CAPSULE_BYTES = 4096
_RECOVERY_INFO = b"ClosedRoom/independent-recovery/v1"
_FIELDS = {"format", "version", "vault_id", "salt", "nonce", "ciphertext"}
_PAYLOAD_FIELDS = {"vault_key", "owner_signer", "owner_public", "checkpoint"}


class RecoveryError(ValueError):
    """The recovery material is invalid or cannot authenticate the capsule."""


@dataclass(frozen=True)
class RecoveredVault:
    vault_id: str
    vault_key: bytes
    owner_signer: Ed25519PrivateKey
    owner_public: bytes
    checkpoint: TrustedCheckpoint


def _id(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 32
            and all(c in "0123456789abcdef" for c in value))


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecoveryError("Invalid recovery encoding") from exc


def _no_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    answer: dict[str, Any] = {}
    for key, value in items:
        if key in answer:
            raise RecoveryError("Duplicate recovery field")
        answer[key] = value
    return answer


def _parse(value: bytes) -> Any:
    try:
        return json.loads(value.decode("utf-8"), object_pairs_hook=_no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(RecoveryError("Invalid JSON constant")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Invalid recovery JSON") from exc


def _b64(value: Any, expected: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise RecoveryError("Invalid recovery field")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RecoveryError("Invalid recovery field") from exc
    if expected is not None and len(result) != expected:
        raise RecoveryError("Invalid recovery field length")
    return result


def _validate_checkpoint(value: TrustedCheckpoint, vault_id: str) -> None:
    if (not isinstance(value, TrustedCheckpoint) or value.vault_id != vault_id
            or type(value.revision) is not int or value.revision < 0
            or type(value.key_epoch) is not int or value.key_epoch < 1
            or not isinstance(value.digest, str) or len(value.digest) != 64
            or any(ch not in "0123456789abcdef" for ch in value.digest)):
        raise RecoveryError("Invalid independently trusted checkpoint")


def generate_recovery_code() -> str:
    """A one-time 256-bit recovery code; app must NOT persist its plaintext."""
    material = secrets.token_bytes(32)
    return "CR1-" + base64.b32encode(material).decode("ascii").rstrip("=")


def _decode_code(value: str) -> bytes:
    # Exact canonical spelling avoids accepting accidental weak passwords.
    if not isinstance(value, str) or not value.startswith("CR1-"):
        raise RecoveryError("Recovery code must be a randomly generated CR1 code")
    encoded = value[4:]
    if len(encoded) != 52 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for ch in encoded):
        raise RecoveryError("Invalid recovery code")
    try:
        raw = base64.b32decode(encoded + "====", casefold=False)
    except (ValueError, binascii.Error) as exc:
        raise RecoveryError("Invalid recovery code") from exc
    if len(raw) != 32 or raw == bytes(32) or generate_code_from_bytes(raw) != value:
        raise RecoveryError("Invalid or degenerate recovery code")
    return raw


def generate_code_from_bytes(raw: bytes) -> str:
    """Canonical encoding of 32 bytes; never call on low-entropy input."""
    if not isinstance(raw, bytes) or len(raw) != 32:
        raise RecoveryError("Recovery material must be 256 bits")
    return "CR1-" + base64.b32encode(raw).decode("ascii").rstrip("=")


def _key(secret: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=_RECOVERY_INFO).derive(secret)


def create_recovery_capsule(
    vault_id: str,
    vault_key: bytes,
    owner_signer: Ed25519PrivateKey,
    checkpoint: TrustedCheckpoint,
    recovery_code: str,
) -> bytes:
    """Encrypt both independent identity secrets, never the recovery code."""
    if not _id(vault_id) or not isinstance(vault_key, bytes) or len(vault_key) != 32:
        raise RecoveryError("Invalid vault")
    if not isinstance(owner_signer, Ed25519PrivateKey):
        raise RecoveryError("Invalid owner signing key")
    _validate_checkpoint(checkpoint, vault_id)
    secret = _decode_code(recovery_code)
    signer_bytes = owner_signer.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    payload = {
        "vault_key": base64.b64encode(vault_key).decode("ascii"),
        "owner_signer": base64.b64encode(signer_bytes).decode("ascii"),
        "owner_public": base64.b64encode(public_key_bytes(owner_signer)).decode("ascii"),
        "checkpoint": asdict(checkpoint),
    }
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = {
        "format": FORMAT, "version": VERSION, "vault_id": vault_id,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    ciphertext = AESGCM(_key(secret, salt)).encrypt(nonce, _canonical(payload), _canonical(header))
    result = _canonical({**header, "ciphertext": base64.b64encode(ciphertext).decode("ascii")})
    if len(result) > MAX_CAPSULE_BYTES:
        raise RecoveryError("Recovery capsule exceeded size budget")
    return result


def open_recovery_capsule(
    document: bytes,
    recovery_code: str,
    *,
    expected_vault_id: str | None = None,
    expected_owner_public: bytes | None = None,
    minimum_checkpoint: TrustedCheckpoint | None = None,
) -> RecoveredVault:
    """Restore offline identity only with independently held 256-bit code.

    expected_owner_public and minimum_checkpoint, if available from a trusted
    non-Drive channel, prevent key substitution and stale-cap replay. With no
    independent minimum checkpoint the provider can replay an older capsule.
    """
    secret = _decode_code(recovery_code)
    if not isinstance(document, bytes) or len(document) > MAX_CAPSULE_BYTES:
        raise RecoveryError("Invalid recovery capsule size")
    data = _parse(document)
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise RecoveryError("Invalid recovery capsule schema")
    if data["format"] != FORMAT or type(data["version"]) is not int or data["version"] != VERSION:
        raise RecoveryError("Unsupported recovery capsule version")
    vault_id = data["vault_id"]
    if not _id(vault_id) or (expected_vault_id is not None and vault_id != expected_vault_id):
        raise RecoveryError("Recovery capsule vault mismatch")
    if expected_owner_public is not None and (not isinstance(expected_owner_public, bytes)
                                              or len(expected_owner_public) != 32):
        raise RecoveryError("Invalid independently pinned owner")
    salt, nonce = _b64(data["salt"], 16), _b64(data["nonce"], 12)
    ciphertext = _b64(data["ciphertext"])
    if len(ciphertext) < 16 or len(ciphertext) > MAX_CAPSULE_BYTES:
        raise RecoveryError("Invalid recovery ciphertext size")
    header = {name: data[name] for name in _FIELDS - {"ciphertext"}}
    try:
        decrypted = AESGCM(_key(secret, salt)).decrypt(nonce, ciphertext, _canonical(header))
    except InvalidTag as exc:
        raise RecoveryError("Recovery code or capsule authentication failed") from exc
    payload = _parse(decrypted)
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise RecoveryError("Invalid recovery payload")
    key = _b64(payload["vault_key"], 32)
    signer_bytes = _b64(payload["owner_signer"], 32)
    owner_public = _b64(payload["owner_public"], 32)
    try:
        signer = Ed25519PrivateKey.from_private_bytes(signer_bytes)
    except ValueError as exc:
        raise RecoveryError("Invalid recovered signing identity") from exc
    if not secrets.compare_digest(public_key_bytes(signer), owner_public):
        raise RecoveryError("Recovery owner identity mismatch")
    if expected_owner_public is not None and not secrets.compare_digest(owner_public, expected_owner_public):
        raise RecoveryError("Unexpected recovered owner")
    checkpoint_raw = payload["checkpoint"]
    if not isinstance(checkpoint_raw, dict) or set(checkpoint_raw) != {
        "vault_id", "revision", "digest", "key_epoch",
    }:
        raise RecoveryError("Invalid recovery checkpoint")
    try:
        checkpoint = TrustedCheckpoint(**checkpoint_raw)
    except (TypeError, ValueError) as exc:
        raise RecoveryError("Invalid recovery checkpoint") from exc
    _validate_checkpoint(checkpoint, vault_id)
    if minimum_checkpoint is not None:
        _validate_checkpoint(minimum_checkpoint, vault_id)
        if (checkpoint.revision < minimum_checkpoint.revision
                or (checkpoint.revision == minimum_checkpoint.revision
                    and checkpoint.digest != minimum_checkpoint.digest)
                or checkpoint.key_epoch < minimum_checkpoint.key_epoch):
            raise RecoveryError("Recovery capsule is stale or conflicts with trusted checkpoint")
    return RecoveredVault(vault_id, key, signer, owner_public, checkpoint)
