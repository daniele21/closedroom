"""Isolated macOS Keychain proof for ClosedRoom secure sync.

No file fallback, transport or implicit initialization. Injected test backends
MUST NOT be used in product code. Genuine macOS Keychain proof is pending.
"""
from __future__ import annotations

import base64
import binascii
import json
import secrets
import sys
from dataclasses import asdict
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vault_manifest import TrustedCheckpoint, verify_manifest

SERVICE = "com.closedroom.app.secure-sync.v1"


class KeychainError(RuntimeError):
    """No safe local secret or trusted checkpoint is available."""


class _Backend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...


def _validate_id(vault_id: str) -> None:
    if not isinstance(vault_id, str) or len(vault_id) != 32 or any(c not in "0123456789abcdef" for c in vault_id):
        raise KeychainError("Invalid vault identifier")


class MacKeychainVaultKeys:
    """Test-only interface until native Mac and process-lock qualification."""

    def __init__(self, *, _test_backend: _Backend | None = None):
        if _test_backend is not None:
            self._backend = _test_backend
            return
        if sys.platform != "darwin":
            raise KeychainError("macOS Keychain required: no fallback")
        try:
            import keyring
            backend = keyring.get_keyring()
        except Exception as exc:
            raise KeychainError("macOS Keychain unavailable") from exc
        if not type(backend).__module__.startswith("keyring.backends.macOS"):
            raise KeychainError("Refusing non-macOS Keychain backend")
        self._backend = backend

    def _get(self, account: str) -> str | None:
        try:
            return self._backend.get_password(SERVICE, account)
        except Exception as exc:
            raise KeychainError("Keychain read failed") from exc

    def _set(self, account: str, value: str) -> None:
        try:
            self._backend.set_password(SERVICE, account, value)
        except Exception as exc:
            raise KeychainError("Keychain write failed") from exc
        if self._get(account) != value:
            raise KeychainError("Keychain readback mismatch")

    def _create_secret(self, account: str, secret: bytes) -> None:
        if self._get(account) is not None:
            raise KeychainError("Keychain identity already exists")
        self._set(account, base64.b64encode(secret).decode("ascii"))

    def _load_secret(self, account: str) -> bytes:
        value = self._get(account)
        if value is None:
            raise KeychainError("Key missing: independent recovery required")
        try:
            result = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error, TypeError) as exc:
            raise KeychainError("Corrupt Keychain value") from exc
        if len(result) != 32:
            raise KeychainError("Invalid Keychain secret length")
        return result

    def create(self, vault_id: str) -> bytes:
        _validate_id(vault_id)
        secret = secrets.token_bytes(32)
        self._create_secret(vault_id + ":master", secret)
        if not secrets.compare_digest(self.load(vault_id), secret):
            raise KeychainError("Vault readback mismatch")
        return secret

    def load(self, vault_id: str) -> bytes:
        _validate_id(vault_id)
        return self._load_secret(vault_id + ":master")

    def create_owner_signer(self, vault_id: str) -> Ed25519PrivateKey:
        """Software signing identity kept in Keychain, NOT Secure Enclave."""
        _validate_id(vault_id)
        signer = Ed25519PrivateKey.generate()
        private = signer.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self._create_secret(vault_id + ":owner-signing", private)
        if self.load_owner_signer(vault_id).public_key().public_bytes_raw() != signer.public_key().public_bytes_raw():
            raise KeychainError("Signing identity readback mismatch")
        return signer

    def load_owner_signer(self, vault_id: str) -> Ed25519PrivateKey:
        _validate_id(vault_id)
        return Ed25519PrivateKey.from_private_bytes(self._load_secret(vault_id + ":owner-signing"))

    def pin_authenticated_owner(self, vault_id: str, public_key: bytes) -> None:
        """Public key MUST come from owner or authenticated out-of-band pairing."""
        _validate_id(vault_id)
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            raise KeychainError("Invalid pinned owner key")
        account = vault_id + ":owner-pin"
        value = base64.b64encode(public_key).decode("ascii")
        existing = self._get(account)
        if existing is not None:
            if not secrets.compare_digest(existing, value):
                raise KeychainError("Pinned owner key cannot be replaced")
            return
        self._set(account, value)

    def load_checkpoint(self, vault_id: str) -> TrustedCheckpoint | None:
        _validate_id(vault_id)
        raw = self._get(vault_id + ":checkpoint")
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != {"vault_id", "revision", "digest", "key_epoch"}:
                raise ValueError("wrong schema")
            value = TrustedCheckpoint(**data)
            if (value.vault_id != vault_id or type(value.revision) is not int or value.revision < 0
                    or type(value.key_epoch) is not int or value.key_epoch < 1
                    or not isinstance(value.digest, str) or len(value.digest) != 64
                    or any(c not in "0123456789abcdef" for c in value.digest)):
                raise ValueError("invalid checkpoint")
            return value
        except (TypeError, ValueError) as exc:
            raise KeychainError("Corrupt trusted checkpoint") from exc

    def accept_signed_head(self, vault_id: str, document: bytes) -> TrustedCheckpoint:
        """One local writer only: production requires cross-process CAS/lock."""
        _validate_id(vault_id)
        pinned = self._load_secret(vault_id + ":owner-pin")
        previous = self.load_checkpoint(vault_id)
        accepted = verify_manifest(document, pinned, previous)
        if accepted.vault_id != vault_id:
            raise KeychainError("Signed head belongs to another vault")
        if accepted != previous:
            self._set(vault_id + ":checkpoint", json.dumps(asdict(accepted), sort_keys=True))
            if self.load_checkpoint(vault_id) != accepted:
                raise KeychainError("Checkpoint readback mismatch")
        return accepted
