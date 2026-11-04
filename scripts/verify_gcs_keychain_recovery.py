#!/usr/bin/env python3
"""Explicit, test-only archive key export/import on macOS Keychain.

Use on two separate Macs to test portability. NEVER point at actual meeting
keys: dedicated fixture Keychain service. Keep the recovery file and displayed
code separate. Do not paste the recovery code into chat, issues or logs.
Requires: PYTHONPATH=src uv run --no-project --with cryptography --with keyring ...
"""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import secrets
import sys

from local_asr_server.storage.key_recovery import (
    ArchiveKeyUnavailable, ArchiveKeyVault, RecoveryFailed,
    create_recovery_envelope, key_fingerprint, load_recovery_file,
    save_recovery_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create-fixture", "restore-fixture", "check-fixture"))
    parser.add_argument("--recovery-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        vault = ArchiveKeyVault(fixture=True)
        if args.action == "create-fixture":
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise RecoveryFailed("An interactive terminal is required for one-time recovery code display")
            # Do not overwrite an existing recovery export, even with the same key.
            if args.recovery_file.exists() or args.recovery_file.is_symlink():
                raise RecoveryFailed("Recovery file already exists")
            key = vault.load()
            if key is None:
                key = secrets.token_bytes(32)
                vault.store_if_absent(key)
            envelope, code = create_recovery_envelope(key)
            save_recovery_file(args.recovery_file, envelope)
            print("TEST-ONLY RECOVERY CODE — SAVE SECURELY AND SEPARATELY:")
            print(code)
            print("Code displayed once; do not paste it into ChatGPT or log files.")
            print("Fixture recovery file created; copy only this file to a second Mac (chmod 600).")
        elif args.action == "restore-fixture":
            envelope = load_recovery_file(args.recovery_file)
            code = getpass.getpass("Fixture recovery code (hidden): ")
            key = vault.import_recovery(envelope, code)
            print("Fixture recovered to native Keychain; fingerprint matches:", key_fingerprint(key) == envelope["key_sha256"])
        else:
            envelope = load_recovery_file(args.recovery_file)
            key = vault.load()
            if key is None:
                raise RecoveryFailed("Fixture key not present in this Mac Keychain")
            print("Fixture stored in native Keychain; fingerprint matches:", key_fingerprint(key) == envelope["key_sha256"])
        return 0
    except (ArchiveKeyUnavailable, RecoveryFailed, OSError):
        print("Fixture key operation failed or was refused; no archive data changed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
