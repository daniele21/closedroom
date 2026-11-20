"""Opt-in synthetic Keychain diagnosis from the actual frozen ClosedRoom.app binary.

The diagnostic neither starts the app API nor reads/writes real meeting or
vault state. It is intentionally inaccessible through network endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import subprocess
import sys

from local_asr_server.macos_keychain_native import (
    MacKeychain, NativeKeychainError, NativeVaultProbeBackend, VAULT_PROBE_SERVICE,
)

COMMAND = "secure-sync-keychain-smoke"
CHILD_COMMAND = "secure-sync-keychain-smoke-child"
VAULT_COMMAND = "secure-sync-native-vault-smoke"
VAULT_CHILD_COMMAND = "secure-sync-native-vault-smoke-child"


def _require_bundle() -> None:
    if not (sys.platform == "darwin" and getattr(sys, "frozen", False)):
        raise NativeKeychainError("This diagnostic requires a frozen macOS ClosedRoom.app")


def _child(account: str, challenge_hex: str) -> int:
    _require_bundle()
    if len(challenge_hex) != 64 or any(c not in "0123456789abcdef" for c in challenge_hex):
        raise NativeKeychainError("Invalid challenge")
    secret = MacKeychain().load(account)
    if secret is None:
        raise NativeKeychainError("Temporary Keychain secret unavailable in second process")
    proof = hmac.digest(secret, bytes.fromhex(challenge_hex), hashlib.sha256)
    print(proof.hex())
    return 0


def run_synthetic_keychain_smoke() -> int:
    """Only run from a signed/ad-hoc frozen app executable in a user GUI session."""
    _require_bundle()
    account = secrets.token_hex(16)
    key = secrets.token_bytes(32)
    store = MacKeychain()
    created = False
    error: BaseException | None = None
    cleaned = False
    try:
        if store.load(account) is not None:
            raise NativeKeychainError("Random synthetic Keychain account collision")
        store.create(account, key)
        created = True
        if not hmac.compare_digest(store.load(account) or b"", key):
            raise NativeKeychainError("First-process Keychain readback failed")
        challenge = secrets.token_bytes(32)
        child = subprocess.run(
            [sys.executable, CHILD_COMMAND, account, challenge.hex()],
            capture_output=True, text=True, timeout=25, check=False,
        )
        if child.returncode != 0:
            raise NativeKeychainError("Second packaged process Keychain access failed")
        try:
            received = bytes.fromhex(child.stdout.strip())
        except ValueError as exc:
            raise NativeKeychainError("Invalid second-process challenge response") from exc
        expected = hmac.digest(key, challenge, hashlib.sha256)
        if not hmac.compare_digest(received, expected):
            raise NativeKeychainError("Second-process challenge verification failed")
    except BaseException as exc:
        error = exc
    finally:
        if created:
            try:
                store.delete(account)
                cleaned = store.load(account) is None
            except Exception:
                cleaned = False
        else:
            # Never delete a pre-existing account or one with ambiguous
            # ownership. A failed SecItemAdd must not touch other key material.
            cleaned = error is None
    if not cleaned:
        raise NativeKeychainError("Synthetic Keychain cleanup not proven") from error
    if error is not None:
        raise NativeKeychainError("Packaged Keychain smoke did not pass") from error
    print(json.dumps({
        "schema": "closedroom.packaged-keychain-smoke/v1",
        "status": "pass",
        "frozen_app_process": True,
        "independent_child": True,
        "synthetic_only": True,
        "cleanup": True,
    }, sort_keys=True))
    return 0


def _vault_child(account: str, challenge_hex: str) -> int:
    _require_bundle()
    if (len(challenge_hex) != 64
            or any(ch not in "0123456789abcdef" for ch in challenge_hex)):
        raise NativeKeychainError("Invalid synthetic challenge")
    backend = NativeVaultProbeBackend()
    stored = backend.get_password(VAULT_PROBE_SERVICE, account)
    if stored is None:
        raise NativeKeychainError("Native vault probe inaccessible from child")
    try:
        key = base64.b64decode(stored, validate=True)
    except Exception as exc:
        raise NativeKeychainError("Corrupt native vault probe secret") from exc
    if len(key) != 32:
        raise NativeKeychainError("Incorrect native vault probe key length")
    print(hmac.digest(key, bytes.fromhex(challenge_hex), hashlib.sha256).hex())
    return 0


def run_native_vault_backend_smoke() -> int:
    """Run a no-meeting-data set/update/read/clear/delete roundtrip as app."""
    _require_bundle()
    vault_id = secrets.token_hex(16)
    account = vault_id + ":master"
    prepare_account = vault_id + ":ledger-prepare"
    backend = NativeVaultProbeBackend()
    created: list[str] = []
    error: BaseException | None = None
    cleaned = False
    try:
        if (backend.get_password(VAULT_PROBE_SERVICE, account) is not None
                or backend.get_password(VAULT_PROBE_SERVICE, prepare_account) is not None):
            raise NativeKeychainError("Random native vault probe identity collision")
        old = secrets.token_bytes(32)
        latest = secrets.token_bytes(32)
        backend.set_password(VAULT_PROBE_SERVICE, account, base64.b64encode(old).decode("ascii"))
        created.append(account)
        backend.set_password(VAULT_PROBE_SERVICE, account, base64.b64encode(latest).decode("ascii"))
        if backend.get_password(VAULT_PROBE_SERVICE, account) != base64.b64encode(latest).decode("ascii"):
            raise NativeKeychainError("Native vault overwrite not readable")
        backend.set_password(VAULT_PROBE_SERVICE, prepare_account, "pending")
        created.append(prepare_account)
        backend.set_password(VAULT_PROBE_SERVICE, prepare_account, "")
        if backend.get_password(VAULT_PROBE_SERVICE, prepare_account) != "":
            raise NativeKeychainError("Native vault preparation clear failed")
        challenge = secrets.token_bytes(32)
        proc = subprocess.run(
            [sys.executable, VAULT_CHILD_COMMAND, account, challenge.hex()],
            capture_output=True, text=True, timeout=25, check=False,
        )
        if proc.returncode != 0:
            raise NativeKeychainError("Second packaged process cannot access updated secret")
        try:
            answer = bytes.fromhex(proc.stdout.strip())
        except ValueError as exc:
            raise NativeKeychainError("Invalid native vault second-process proof") from exc
        if not hmac.compare_digest(answer, hmac.digest(latest, challenge, hashlib.sha256)):
            raise NativeKeychainError("Native vault second-process key mismatch")
    except BaseException as exc:
        error = exc
    finally:
        try:
            for item in reversed(created):
                backend.delete_password(VAULT_PROBE_SERVICE, item)
            cleaned = (
                backend.get_password(VAULT_PROBE_SERVICE, account) is None
                and backend.get_password(VAULT_PROBE_SERVICE, prepare_account) is None
            )
        except Exception:
            cleaned = False
    if not cleaned:
        raise NativeKeychainError("Native vault probe cleanup could not be verified") from error
    if error is not None:
        raise NativeKeychainError("Native vault Keychain probe failed") from error
    print(json.dumps({
        "schema": "closedroom.native-vault-probe/v1",
        "status": "pass",
        "independent_child": True,
        "updated_item": True,
        "empty_preparation": True,
        "cleanup": True,
        "synthetic_only": True,
    }, sort_keys=True))
    return 0


def dispatch_keychain_probe(argv: list[str]) -> bool:
    """Recognize only diagnostic commands; reject malformed invocations."""
    if len(argv) < 2 or argv[1] not in (
        COMMAND, CHILD_COMMAND, VAULT_COMMAND, VAULT_CHILD_COMMAND,
    ):
        return False
    if len(argv) == 2 and argv[1] == COMMAND:
        run_synthetic_keychain_smoke()
    elif len(argv) == 4 and argv[1] == CHILD_COMMAND:
        _child(argv[2], argv[3])
    elif len(argv) == 2 and argv[1] == VAULT_COMMAND:
        run_native_vault_backend_smoke()
    elif len(argv) == 4 and argv[1] == VAULT_CHILD_COMMAND:
        _vault_child(argv[2], argv[3])
    else:
        raise SystemExit("Invalid packaged Keychain diagnostic arguments")
    return True
