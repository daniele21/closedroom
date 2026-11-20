"""Opt-in, offline-only encrypted transcript snapshot format (no transport or keys at rest).

Never call this module from recording finalization. A caller must explicitly
select what to export and persist the vault key in an OS-protected owner.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

FORMAT = "closedroom.encrypted-transcript"
VERSION = 1
MAX_PLAINTEXT_BYTES = 8 * 1024 * 1024
MAX_ENVELOPE_BYTES = 12 * 1024 * 1024
_HEADER_FIELDS = frozenset({"format", "version", "object_id", "salt", "nonce"})
_ENVELOPE_FIELDS = _HEADER_FIELDS | {"ciphertext"}


class SecureSyncError(ValueError):
    """A malformed, unsupported or unauthenticated snapshot."""


def generate_vault_key() -> bytes:
    """Create a secret. The caller MUST securely persist/backup it outside Drive."""
    return secrets.token_bytes(32)


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != 32:
        raise SecureSyncError("A 32-byte vault key is required")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise SecureSyncError("Duplicate field in encrypted snapshot")
        result[name] = value
    return result


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(SecureSyncError("Invalid JSON constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecureSyncError("Invalid encrypted snapshot encoding") from exc


def _decode_field(value: Any, expected_length: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise SecureSyncError("Invalid encrypted snapshot field")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SecureSyncError("Invalid encrypted snapshot field") from exc
    if expected_length is not None and len(decoded) != expected_length:
        raise SecureSyncError("Invalid encrypted snapshot field length")
    return decoded


def transcript_snapshot(
    transcription: Mapping[str, Any], *, title: str = "", notes: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Allowlist read-only content from canonical stores; never copy raw metadata.

    This is a snapshot projection, not an importer or a transactional multi-store
    read. Capture consistency and versioned sync will be addressed separately.
    """
    if not isinstance(transcription, Mapping) or not isinstance(transcription.get("id"), str) or not transcription["id"]:
        raise SecureSyncError("Missing transcription identity")
    if not isinstance(transcription.get("text"), str) or not isinstance(title, str):
        raise SecureSyncError("Invalid transcription text or title")
    if not isinstance(notes, (list, tuple)):
        raise SecureSyncError("Invalid notes")
    projected_notes = []
    for note in notes:
        if not isinstance(note, Mapping) or not isinstance(note.get("note_id"), str) or not isinstance(note.get("text"), str):
            raise SecureSyncError("Invalid note")
        projected_notes.append({
            "note_id": note["note_id"], "text": note["text"],
            "timestamp": note.get("timestamp"), "revision": note.get("revision"),
        })
    return {
        "schema": 1,
        "kind": "transcription_readonly",
        "transcription_id": transcription["id"],
        "recording_id": transcription.get("recording_id") or "",
        "title": title,
        "timestamp": transcription.get("timestamp"),
        "language": transcription.get("language"),
        "text": transcription["text"],
        "segments": transcription.get("segments") or [],
        "analysis": transcription.get("analysis"),
        "speaker_diarization": transcription.get("speaker_diarization"),
        "speaker_attribution": transcription.get("speaker_attribution"),
        "notes": projected_notes,
    }


def seal_snapshot(snapshot: Mapping[str, Any], vault_key: bytes) -> bytes:
    """Encrypt a read-only transcript with HKDF-SHA256/AES-256-GCM.

    Object identifiers and sizes are visible to the provider. Contents, IDs,
    speaker names and titles are authenticated ciphertext. No network I/O.
    """
    _validate_key(vault_key)
    if not isinstance(snapshot, Mapping) or snapshot.get("schema") != 1 or snapshot.get("kind") != "transcription_readonly":
        raise SecureSyncError("Unsupported transcript snapshot")
    try:
        plaintext = _json_bytes(dict(snapshot))
    except (TypeError, ValueError, OverflowError) as exc:
        raise SecureSyncError("Invalid transcript snapshot contents") from exc
    if len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise SecureSyncError("Transcript snapshot exceeds size limit")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    header = {
        "format": FORMAT, "version": VERSION,
        "object_id": secrets.token_hex(16),
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"ClosedRoom/transcript-snapshot/v1").derive(vault_key)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _json_bytes(header))
    result = _json_bytes({**header, "ciphertext": base64.b64encode(ciphertext).decode("ascii")})
    if len(result) > MAX_ENVELOPE_BYTES:
        raise SecureSyncError("Encrypted snapshot exceeds size limit")
    return result


def open_snapshot(envelope: bytes, vault_key: bytes) -> dict[str, Any]:
    """Fail closed on malformed format, unauthenticated metadata or wrong key."""
    _validate_key(vault_key)
    if not isinstance(envelope, bytes) or len(envelope) > MAX_ENVELOPE_BYTES:
        raise SecureSyncError("Invalid encrypted snapshot size")
    package = _parse_json(envelope)
    if not isinstance(package, dict) or set(package) != _ENVELOPE_FIELDS:
        raise SecureSyncError("Invalid encrypted snapshot fields")
    if package["format"] != FORMAT or type(package["version"]) is not int or package["version"] != VERSION:
        raise SecureSyncError("Unsupported encrypted snapshot version")
    object_id = package["object_id"]
    if not isinstance(object_id, str) or len(object_id) != 32 or any(c not in "0123456789abcdef" for c in object_id):
        raise SecureSyncError("Invalid object identity")
    salt = _decode_field(package["salt"], 16)
    nonce = _decode_field(package["nonce"], 12)
    ciphertext = _decode_field(package["ciphertext"])
    if len(ciphertext) < 16 or len(ciphertext) > MAX_PLAINTEXT_BYTES + 16:
        raise SecureSyncError("Invalid ciphertext length")
    header = {name: package[name] for name in _HEADER_FIELDS}
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"ClosedRoom/transcript-snapshot/v1").derive(vault_key)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _json_bytes(header))
    except InvalidTag as exc:
        raise SecureSyncError("Encrypted snapshot authentication failed") from exc
    snapshot = _parse_json(plaintext)
    if not isinstance(snapshot, dict) or snapshot.get("schema") != 1 or snapshot.get("kind") != "transcription_readonly":
        raise SecureSyncError("Unsupported decrypted transcript snapshot")
    return snapshot
