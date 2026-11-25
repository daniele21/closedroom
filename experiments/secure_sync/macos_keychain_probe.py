"""Opt-in real macOS Keychain smoke on a trusted, nonisolated Mac runner.

Test data only. This must never receive a real user vault ID, transcript,
Google credentials or recovery material. Exits nonzero if backend, second
process re-read or cleanup is not proven. No content is uploaded or logged.
"""
from __future__ import annotations

import base64
import json
import secrets
import subprocess
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from vault_keychain import MacKeychainVaultKeys, SERVICE
from vault_manifest import new_manifest, sign_manifest

_CLEANUP_SUFFIXES = (":checkpoint", ":owner-pin", ":owner-signing", ":master")
_MESSAGE = b"closedroom-synthetic-keychain-smoke/v1"


def _child(vault_id: str) -> int:
    # Child has no private bytes in argv/env; reads Keychain directly.
    payload = json.loads(sys.stdin.buffer.read(16384))
    vault = MacKeychainVaultKeys()
    nonce = base64.b64decode(payload["nonce"], validate=True)
    ciphertext = base64.b64decode(payload["ciphertext"], validate=True)
    if AESGCM(vault.load(vault_id)).decrypt(nonce, ciphertext, b"closedroom-smoke") != _MESSAGE:
        raise RuntimeError("Second process could not retrieve the vault key")
    signer = vault.load_owner_signer(vault_id)
    checkpoint = vault.load_checkpoint(vault_id)
    if checkpoint is None or checkpoint.revision != 0:
        raise RuntimeError("Second process did not recover signed checkpoint")
    signature = signer.sign(base64.b64decode(payload["challenge"], validate=True))
    sys.stdout.write(base64.b64encode(signature).decode("ascii"))
    return 0


def _parent() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("Real macOS Keychain required; no non-Mac fallback")
    vault_id = secrets.token_hex(16)
    vault = MacKeychainVaultKeys()  # Must enforce real macOS Keychain.
    backend = vault._backend  # Only probe cleanup, not a production interface.
    accounts = [vault_id + suffix for suffix in _CLEANUP_SUFFIXES]
    safe_to_cleanup = False
    primary_error: BaseException | None = None
    cleanup_errors: list[str] = []
    try:
        # Never overwrite existing entries even if an astronomically unlikely
        # collision occurs. Validate all accounts first.
        if any(backend.get_password(SERVICE, account) is not None for account in accounts):
            raise RuntimeError("Random synthetic Keychain identity collision")
        safe_to_cleanup = True
        key = vault.create(vault_id)
        signer = vault.create_owner_signer(vault_id)
        vault.pin_authenticated_owner(vault_id, signer.public_key().public_bytes_raw())
        genesis = sign_manifest(new_manifest(
            vault_id=vault_id, revision=0, previous=None,
        ), signer)
        vault.accept_signed_head(vault_id, genesis)
        nonce = secrets.token_bytes(12)
        challenge = secrets.token_bytes(32)
        request = json.dumps({
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(
                AESGCM(key).encrypt(nonce, _MESSAGE, b"closedroom-smoke"),
            ).decode("ascii"),
            "challenge": base64.b64encode(challenge).decode("ascii"),
        })
        completed = subprocess.run(
            [sys.executable, __file__, "--child", vault_id],
            input=request, text=True, capture_output=True, timeout=20, check=True,
        )
        signature = base64.b64decode(completed.stdout.strip(), validate=True)
        try:
            signer.public_key().verify(signature, challenge)
        except InvalidSignature as exc:
            raise RuntimeError("Second process failed to prove signing-key access") from exc
    except BaseException as exc:
        primary_error = exc
    finally:
        for account in (accounts if safe_to_cleanup else []):
            try:
                if backend.get_password(SERVICE, account) is not None:
                    backend.delete_password(SERVICE, account)
                if backend.get_password(SERVICE, account) is not None:
                    cleanup_errors.append(account.rsplit(":", 1)[-1])
            except Exception:
                cleanup_errors.append(account.rsplit(":", 1)[-1])
    if cleanup_errors:
        raise RuntimeError("Synthetic Keychain cleanup failed: " + ", ".join(cleanup_errors)) from primary_error
    if primary_error is not None:
        raise RuntimeError("Real Keychain smoke failed; no secrets were printed") from primary_error
    print("REAL_MAC_KEYCHAIN_SMOKE=PASS second_process=true cleanup=true synthetic_only=true")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(_child(sys.argv[2]))
    if len(sys.argv) != 1:
        raise SystemExit("Unexpected arguments")
    raise SystemExit(_parent())
