"""ClosedRoom archive encryption key: native macOS Keychain and portable recovery.

This module is not wired to meeting capture. No cloud or credential fallback,
no logging of keys, no implicit recovery export, no deletion/rotation.
A recovery JSON alone cannot unlock the archive: its randomly generated
recovery code must be kept separately. Only the user explicitly exports it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any

KEY_BYTES = 32
FORMAT = "closedroom-archive-key-recovery-v1"
AAD = b"ClosedRoom archive master key recovery v1"
KEYCHAIN_SERVICE = "com.closedroom.app.gcs.archive"
FIXTURE_SERVICE = "com.closedroom.app.gcs.fixture"
_ACCOUNT = "master-key-v1"
_RECOVERY_PATTERN = re.compile(r"CR1-[A-Za-z0-9_-]{43}\Z")
_MAX_FILE_BYTES = 4096


class ArchiveKeyUnavailable(RuntimeError):
    """No unlocked archive key, or the designated secure backend is unavailable."""


class RecoveryFailed(ValueError):
    """Recovery material was invalid or failed authenticated decryption."""


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
    except ImportError as exc:
        raise ArchiveKeyUnavailable("Archive recovery requires cryptography") from exc
    return AESGCM, HKDF, hashes


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: Any, length: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise RecoveryFailed("Invalid recovery material encoding")
    try:
        result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error):
        raise RecoveryFailed("Invalid recovery material encoding") from None
    if len(result) != length or _encode(result) != value:
        raise RecoveryFailed("Invalid recovery material length")
    return result


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise ArchiveKeyUnavailable("Archive encryption key must be 32 bytes")


def key_fingerprint(key: bytes) -> str:
    _validate_key(key)
    # A random 256-bit key is not inferable from its digest; no content included.
    return hashlib.sha256(key).hexdigest()


def create_recovery_envelope(key: bytes) -> tuple[dict[str, Any], str]:
    """Returns encrypted recovery envelope and a one-time 256-bit code.

    The caller must show the code once using a privacy-preserving UX.
    Never store code alongside the envelope, including in logging or analytics.
    """
    _validate_key(key)
    AESGCM, HKDF, hashes = _aesgcm()
    secret = secrets.token_bytes(KEY_BYTES)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=AAD).derive(secret)
    ciphertext = AESGCM(derived).encrypt(nonce, key, AAD)
    return ({
        "format": FORMAT, "kdf": "HKDF-SHA256", "aead": "AES-256-GCM",
        "salt": _encode(salt), "nonce": _encode(nonce),
        "ciphertext": _encode(ciphertext),
        "key_sha256": key_fingerprint(key),
    }, "CR1-" + _encode(secret))


def recover_key(envelope: dict[str, Any], recovery_code: str) -> bytes:
    if not isinstance(envelope, dict) or set(envelope) != {
        "format", "kdf", "aead", "salt", "nonce", "ciphertext", "key_sha256"
    } or envelope["format"] != FORMAT or envelope["kdf"] != "HKDF-SHA256" or envelope["aead"] != "AES-256-GCM":
        raise RecoveryFailed("Unsupported recovery envelope")
    if not isinstance(recovery_code, str) or not _RECOVERY_PATTERN.fullmatch(recovery_code):
        raise RecoveryFailed("Invalid recovery code")
    secret = _decode(recovery_code[4:], KEY_BYTES)
    salt = _decode(envelope["salt"], 16)
    nonce = _decode(envelope["nonce"], 12)
    ciphertext = _decode(envelope["ciphertext"], KEY_BYTES + 16)
    expected = envelope["key_sha256"]
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise RecoveryFailed("Invalid recovery fingerprint")
    AESGCM, HKDF, hashes = _aesgcm()
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=AAD).derive(secret)
    try:
        key = AESGCM(derived).decrypt(nonce, ciphertext, AAD)
    except Exception:
        raise RecoveryFailed("Recovery code or envelope authentication failed") from None
    if key_fingerprint(key) != expected:
        raise RecoveryFailed("Recovered key fingerprint mismatch")
    return key


def save_recovery_file(path: Path, envelope: dict[str, Any]) -> None:
    """Explicit export: create 0600 once; never replace or follow a symlink."""
    data = (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > _MAX_FILE_BYTES:
        raise RecoveryFailed("Recovery envelope exceeds size limit")
    path = Path(path)
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise RecoveryFailed("Recovery export directory must already exist")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def load_recovery_file(path: Path) -> dict[str, Any]:
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > _MAX_FILE_BYTES:
        raise RecoveryFailed("Recovery file must be private (0600), regular and small")
    # Read through O_NOFOLLOW to prevent symlink replacement between lstat/open.
    flags = os.O_RDONLY | (getattr(os, "O_NOFOLLOW", 0))
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        actual = os.fstat(stream.fileno())
        if not stat.S_ISREG(actual.st_mode) or actual.st_mode & 0o077 or actual.st_size > _MAX_FILE_BYTES:
            raise RecoveryFailed("Recovery file must be private (0600), regular and small")
        data = stream.read(_MAX_FILE_BYTES + 1)
    try:
        envelope = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise RecoveryFailed("Malformed recovery file") from None
    if not isinstance(envelope, dict):
        raise RecoveryFailed("Malformed recovery file")
    return envelope


def native_macos_keychain():
    """Use only the native macOS backend, never a keyring fallback or gcloud."""
    if sys.platform != "darwin":
        raise ArchiveKeyUnavailable("macOS Keychain is required")
    try:
        from keyring.backends.macOS import Keyring
        return Keyring()
    except Exception:
        raise ArchiveKeyUnavailable("Native macOS Keychain backend unavailable") from None


class ArchiveKeyVault:
    """Keychain ownership. Injectable backend permits deterministic fake tests."""
    def __init__(self, backend: Any = None, *, fixture: bool = False):
        self._backend = backend if backend is not None else native_macos_keychain()
        self._service = FIXTURE_SERVICE if fixture else KEYCHAIN_SERVICE

    def load(self) -> bytes | None:
        try:
            stored = self._backend.get_password(self._service, _ACCOUNT)
        except Exception:
            raise ArchiveKeyUnavailable("Cannot access macOS Keychain") from None
        if stored is None:
            return None
        key = _decode(stored, KEY_BYTES)
        _validate_key(key)
        return key

    def store_if_absent(self, key: bytes) -> None:
        _validate_key(key)
        if self.load() is not None:
            raise ArchiveKeyUnavailable("Archive key already exists; rotation is not automatic")
        try:
            self._backend.set_password(self._service, _ACCOUNT, _encode(key))
        except Exception:
            raise ArchiveKeyUnavailable("Could not store archive key in macOS Keychain") from None
        if self.load() != key:
            raise ArchiveKeyUnavailable("Archive key write could not be verified")

    def import_recovery(self, envelope: dict[str, Any], code: str) -> bytes:
        key = recover_key(envelope, code)
        present = self.load()
        if present is not None:
            if not secrets.compare_digest(present, key):
                raise ArchiveKeyUnavailable("Existing archive key differs; refusing overwrite")
            return present
        self.store_if_absent(key)
        return key
