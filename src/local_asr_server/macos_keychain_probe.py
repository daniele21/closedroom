"""Opt-in synthetic Keychain diagnosis from the actual frozen ClosedRoom.app binary.

The diagnostic neither starts the app API nor reads/writes real meeting or
vault state. It is intentionally inaccessible through network endpoints.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import subprocess
import sys

from local_asr_server.macos_keychain_native import MacKeychain, NativeKeychainError

COMMAND = "secure-sync-keychain-smoke"
CHILD_COMMAND = "secure-sync-keychain-smoke-child"


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


def dispatch_keychain_probe(argv: list[str]) -> bool:
    """Recognize only diagnostic commands; reject malformed invocations."""
    if len(argv) > 1 and argv[1] in (COMMAND, CHILD_COMMAND):
        if argv[1] == COMMAND and len(argv) == 2:
            run_synthetic_keychain_smoke()
        elif argv[1] == CHILD_COMMAND and len(argv) == 4:
            _child(argv[2], argv[3])
        else:
            raise SystemExit("Invalid packaged Keychain diagnostic arguments")
        return True
    return False
