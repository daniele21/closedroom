"""Offline, authenticated read-only device grant proof for ClosedRoom.

No Google sign-in or Drive object authorizes a device. Enrollment needs a
manual comparison on BOTH devices and an owner public key authenticated from
a channel outside the untrusted transport. The operator-confirmation argument
is a proof boundary; the real UX, durable nonce registry and revocation
policy are not implemented.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from vault_manifest import TrustedCheckpoint, public_key_bytes

_REQUEST_FORMAT = "closedroom.device-pairing-request"
_GRANT_FORMAT = "closedroom.readonly-device-grant"
_VERSION = 1
_MAX_REQUEST_BYTES = 2048
_MAX_GRANT_BYTES = 4096
_TTL_SECONDS = 300
_SKEW_SECONDS = 60
_REQUEST_FIELDS = {"format", "version", "vault_id", "request_id", "device_id",
                   "recipient_public", "issued_at", "expires_at", "permission"}
_GRANT_FIELDS = {"format", "version", "vault_id", "request_sha256", "request_id",
                 "device_id", "recipient_public", "owner_public", "permission",
                 "issued_at", "expires_at", "checkpoint", "sender_public",
                 "salt", "nonce", "ciphertext"}
_DOCUMENT_FIELDS = {"grant", "signature"}


class PairingError(ValueError):
    """A stale, unapproved, unauthenticated or malformed device grant."""


@dataclass
class PendingDevice:
    request: bytes
    recipient_private: X25519PrivateKey
    consumed: bool = False   # Proof only; production must persist this atomically.


@dataclass(frozen=True)
class ReadOnlyGrant:
    vault_id: str
    device_id: str
    vault_key: bytes
    checkpoint: TrustedCheckpoint
    owner_public: bytes
    permission: str = "read_only"


def _hex(value: Any, n: int) -> bool:
    return isinstance(value, str) and len(value) == n and all(ch in "0123456789abcdef" for ch in value)


def _serialize(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise PairingError("Invalid pairing encoding") from exc


def _dedupe(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, value in pairs:
        if name in data:
            raise PairingError("Duplicate pairing JSON field")
        data[name] = value
    return data


def _parse(raw: bytes, max_size: int) -> Any:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= max_size:
        raise PairingError("Invalid pairing document size")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_dedupe,
                          parse_constant=lambda _: (_ for _ in ()).throw(PairingError("Invalid JSON constant")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairingError("Invalid pairing JSON") from exc


def _b64(value: Any, n: int) -> bytes:
    if not isinstance(value, str):
        raise PairingError("Invalid pairing data")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PairingError("Invalid pairing data") from exc
    if len(result) != n:
        raise PairingError("Invalid pairing data length")
    return result


def _validate_checkpoint(checkpoint: TrustedCheckpoint, vault_id: str) -> None:
    if (not isinstance(checkpoint, TrustedCheckpoint) or checkpoint.vault_id != vault_id
            or type(checkpoint.revision) is not int or checkpoint.revision < 0
            or type(checkpoint.key_epoch) is not int or checkpoint.key_epoch < 1
            or not _hex(checkpoint.digest, 64)):
        raise PairingError("Invalid trusted owner checkpoint")


def _request(raw: bytes, now: int) -> dict[str, Any]:
    request = _parse(raw, _MAX_REQUEST_BYTES)
    if not isinstance(request, dict) or set(request) != _REQUEST_FIELDS:
        raise PairingError("Invalid pairing request schema")
    if (request["format"] != _REQUEST_FORMAT or type(request["version"]) is not int
            or request["version"] != _VERSION or request["permission"] != "read_only"):
        raise PairingError("Unsupported pairing request")
    if (not _hex(request["vault_id"], 32) or not _hex(request["request_id"], 32)
            or not _hex(request["device_id"], 32)):
        raise PairingError("Invalid pairing identity")
    _b64(request["recipient_public"], 32)
    issued, expiry = request["issued_at"], request["expires_at"]
    if (type(now) is not int or now < 0 or type(issued) is not int
            or type(expiry) is not int or issued < 0
            or not 0 < expiry - issued <= _TTL_SECONDS
            or now < issued - _SKEW_SECONDS or now >= expiry):
        raise PairingError("Expired or invalid device pairing request")
    return request


def _sas(raw: bytes) -> str:
    # Deterministic 8 digits derived from all canonical request properties.
    digest = hashlib.sha256(b"ClosedRoom/pairing-display/v1\x00" + raw).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 100_000_000:08d}"


def create_device_request(vault_id: str, *, now: int | None = None) -> PendingDevice:
    """Initiate on the new Mac; private X25519 key is never serialized."""
    if not _hex(vault_id, 32):
        raise PairingError("Invalid vault id")
    now = int(time.time()) if now is None else now
    if type(now) is not int or now < 0:
        raise PairingError("Invalid request time")
    private = X25519PrivateKey.generate()
    request = {
        "format": _REQUEST_FORMAT, "version": _VERSION, "vault_id": vault_id,
        "request_id": secrets.token_hex(16), "device_id": secrets.token_hex(16),
        "recipient_public": base64.b64encode(private.public_key().public_bytes_raw()).decode("ascii"),
        "issued_at": now, "expires_at": now + _TTL_SECONDS, "permission": "read_only",
    }
    return PendingDevice(_serialize(request), private)


def comparison_code(request: bytes, *, now: int | None = None) -> str:
    """Display identically on both screens; user MUST compare out of band."""
    now = int(time.time()) if now is None else now
    data = _request(request, now)
    return _sas(_serialize(data))


def _grant_key(private: X25519PrivateKey, peer: bytes, salt: bytes) -> bytes:
    try:
        shared = private.exchange(X25519PublicKey.from_public_bytes(peer))
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                    info=b"ClosedRoom/readonly-pairing/v1").derive(shared)
    except ValueError as exc:
        raise PairingError("Invalid peer device public key") from exc


def authorize_readonly_device(
    request: bytes,
    owner_signer: Ed25519PrivateKey,
    vault_key: bytes,
    checkpoint: TrustedCheckpoint,
    *,
    manually_compared_code: str,
    explicit_approval: bool,
    now: int | None = None,
) -> bytes:
    """On owner's Mac: REQUIRE manual two-screen SAS match and explicit approval.

    The API cannot prove a human compared screens; production UI must supply
    this confirmation ONLY from a real user action, never auto-calculate it.
    """
    now = int(time.time()) if now is None else now
    data = _request(request, now)
    vault_id = data["vault_id"]
    if (type(explicit_approval) is not bool or not explicit_approval
            or not isinstance(manually_compared_code, str)
            or not hmac.compare_digest(manually_compared_code, _sas(_serialize(data)))):
        raise PairingError("Manual pairing verification and approval required")
    if not isinstance(vault_key, bytes) or len(vault_key) != 32:
        raise PairingError("Invalid owner vault key")
    if not isinstance(owner_signer, Ed25519PrivateKey):
        raise PairingError("Owner signing authority required")
    _validate_checkpoint(checkpoint, vault_id)
    sender = X25519PrivateKey.generate()
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = {
        "format": _GRANT_FORMAT, "version": _VERSION, "vault_id": vault_id,
        "request_sha256": hashlib.sha256(_serialize(data)).hexdigest(),
        "request_id": data["request_id"], "device_id": data["device_id"],
        "recipient_public": data["recipient_public"],
        "owner_public": base64.b64encode(public_key_bytes(owner_signer)).decode("ascii"),
        "permission": "read_only", "issued_at": now, "expires_at": data["expires_at"],
        "checkpoint": asdict(checkpoint),
        "sender_public": base64.b64encode(sender.public_key().public_bytes_raw()).decode("ascii"),
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    cipher = AESGCM(_grant_key(sender, _b64(data["recipient_public"], 32), salt)).encrypt(
        nonce, vault_key, _serialize(header))
    grant = {**header, "ciphertext": base64.b64encode(cipher).decode("ascii")}
    signature = owner_signer.sign(_serialize(grant))
    result = _serialize({"grant": grant, "signature": base64.b64encode(signature).decode("ascii")})
    if len(result) > _MAX_GRANT_BYTES:
        raise PairingError("Pairing grant too large")
    return result


def receive_readonly_device(
    pending: PendingDevice,
    grant_document: bytes,
    *,
    independently_authenticated_owner: bytes,
    now: int | None = None,
    minimum_checkpoint: TrustedCheckpoint | None = None,
) -> ReadOnlyGrant:
    """On new Mac: signed decryptable grant bound to OUR unique pending request.

    The authenticated owner public key MUST be obtained via independent
    pairing/recovery proof, NOT accepted from the grant or Drive itself.
    """
    now = int(time.time()) if now is None else now
    if not isinstance(pending, PendingDevice) or pending.consumed:
        raise PairingError("Pairing request already consumed or invalid")
    request = _request(pending.request, now)
    if (not isinstance(independently_authenticated_owner, bytes)
            or len(independently_authenticated_owner) != 32):
        raise PairingError("Authenticated owner public key required")
    expected_public = pending.recipient_private.public_key().public_bytes_raw()
    if not hmac.compare_digest(expected_public, _b64(request["recipient_public"], 32)):
        raise PairingError("Pairing private key does not match request")
    document = _parse(grant_document, _MAX_GRANT_BYTES)
    if not isinstance(document, dict) or set(document) != _DOCUMENT_FIELDS:
        raise PairingError("Invalid signed device grant")
    grant = document["grant"]
    if not isinstance(grant, dict) or set(grant) != _GRANT_FIELDS:
        raise PairingError("Invalid device grant schema")
    if (grant["format"] != _GRANT_FORMAT or type(grant["version"]) is not int
            or grant["version"] != _VERSION or grant["permission"] != "read_only"
            or grant["vault_id"] != request["vault_id"]
            or grant["request_id"] != request["request_id"]
            or grant["device_id"] != request["device_id"]
            or grant["recipient_public"] != request["recipient_public"]
            or grant["request_sha256"] != hashlib.sha256(_serialize(request)).hexdigest()
            or type(grant["issued_at"]) is not int
            or type(grant["expires_at"]) is not int
            or grant["expires_at"] != request["expires_at"]
            or not request["issued_at"] - _SKEW_SECONDS <= grant["issued_at"] < grant["expires_at"]):
        raise PairingError("Unbound or expired device grant")
    public = _b64(grant["owner_public"], 32)
    if not hmac.compare_digest(public, independently_authenticated_owner):
        raise PairingError("Untrusted owner signature")
    signature = _b64(document["signature"], 64)
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, _serialize(grant))
    except (InvalidSignature, ValueError) as exc:
        raise PairingError("Device grant signature failed") from exc
    checkpoint_raw = grant["checkpoint"]
    if not isinstance(checkpoint_raw, dict) or set(checkpoint_raw) != {
        "vault_id", "revision", "digest", "key_epoch",
    }:
        raise PairingError("Invalid signed checkpoint")
    try:
        checkpoint = TrustedCheckpoint(**checkpoint_raw)
    except (ValueError, TypeError) as exc:
        raise PairingError("Invalid signed checkpoint") from exc
    _validate_checkpoint(checkpoint, request["vault_id"])
    if minimum_checkpoint is not None:
        _validate_checkpoint(minimum_checkpoint, request["vault_id"])
        if (checkpoint.revision < minimum_checkpoint.revision
                or (checkpoint.revision == minimum_checkpoint.revision
                    and checkpoint.digest != minimum_checkpoint.digest)
                or checkpoint.key_epoch < minimum_checkpoint.key_epoch):
            raise PairingError("Old or conflicting signed checkpoint")
    salt, nonce = _b64(grant["salt"], 16), _b64(grant["nonce"], 12)
    sender_pub = _b64(grant["sender_public"], 32)
    cipher = _b64(grant["ciphertext"], 48)
    header = {k: v for k, v in grant.items() if k != "ciphertext"}
    try:
        secret = AESGCM(_grant_key(pending.recipient_private, sender_pub, salt)).decrypt(
            nonce, cipher, _serialize(header))
    except InvalidTag as exc:
        raise PairingError("Device grant authentication failed") from exc
    if len(secret) != 32:
        raise PairingError("Invalid decrypted vault key")
    pending.consumed = True
    return ReadOnlyGrant(request["vault_id"], request["device_id"], secret, checkpoint, public)
