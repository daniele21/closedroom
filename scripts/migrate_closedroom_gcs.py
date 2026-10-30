#!/usr/bin/env python3
"""Manual *cold* ClosedRoom GCS migration; no automatic meeting upload.

Backup on Mac A -> move private receipt + encrypted recovery envelope to Mac B
-> import with separately kept recovery code -> optionally activate local app.
For safety, quit ClosedRoom completely on both Macs before use.
"""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

from local_asr_server.storage.cold_migration import (
    DEFAULT_CATALOG, DEFAULT_SETTINGS, MigrationBlocked, upload_snapshot,
    restore_snapshot, activate_import,
)
from local_asr_server.storage.gcs_oauth import OAuthUnavailable
from local_asr_server.storage.key_recovery import ArchiveKeyUnavailable, RecoveryFailed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore", "activate"))
    parser.add_argument("--client-json", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--recovery-file", type=Path)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--settings-file", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-real-meeting-data", action="store_true",
                        help="Required on backup: explicit export of private meeting data to test GCS bucket")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps({"status": "blocked", "error_code": "EXPLICIT_APPLY_REQUIRED"}), file=sys.stderr)
        return 2
    try:
        if args.action == "backup":
            if not args.allow_real_meeting_data:
                raise MigrationBlocked("REAL_MEETING_UPLOAD_CONSENT_REQUIRED")
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise MigrationBlocked("INTERACTIVE_TERMINAL_REQUIRED_FOR_RECOVERY_CODE")
            if not all([args.client_json, args.receipt, args.recovery_file, args.work_dir]):
                raise MigrationBlocked("BACKUP_ARGUMENTS_REQUIRED")
            result, code = upload_snapshot(
                client_json=args.client_json, settings_file=args.settings_file,
                catalog=args.catalog, work_dir=args.work_dir,
                receipt=args.receipt, recovery_file=args.recovery_file,
            )
            print(json.dumps(result, sort_keys=True))
            print("ONE-TIME REAL ARCHIVE RECOVERY CODE — SAVE SEPARATELY, NEVER SHARE:")
            print(code)
            print("Keep receipt and encrypted recovery JSON privately on Mac B; never upload the code.")
        elif args.action == "restore":
            if not all([args.client_json, args.receipt, args.recovery_file, args.target]):
                raise MigrationBlocked("RESTORE_ARGUMENTS_REQUIRED")
            if not sys.stdin.isatty():
                raise MigrationBlocked("INTERACTIVE_TERMINAL_REQUIRED_FOR_RECOVERY_CODE")
            code = getpass.getpass("ClosedRoom real-archive recovery code (hidden): ")
            result = restore_snapshot(
                client_json=args.client_json, receipt=args.receipt,
                recovery_file=args.recovery_file, recovery_code=code,
                target=args.target, work_dir=args.work_dir,
            )
            print(json.dumps(result, sort_keys=True))
        else:
            if not args.target:
                raise MigrationBlocked("TARGET_REQUIRED")
            result = activate_import(args.target, args.settings_file)
            print(json.dumps(result, sort_keys=True))
        return 0
    except MigrationBlocked as exc:
        code = str(exc)
    except OAuthUnavailable as exc:
        code = exc.code
    except (ArchiveKeyUnavailable, RecoveryFailed):
        code = "KEYCHAIN_OR_RECOVERY_FAILED"
    except Exception:
        # SDK/OS exceptions can contain local paths or credential information.
        code = "MIGRATION_FAILED_INSPECT_PRIVATE_MAC_LOGS"
    print(json.dumps({"status": "blocked", "error_code": code}, sort_keys=True),
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
