#!/usr/bin/env python3
"""Deliberate Mac-only headless cold-backup runner entrypoint.

Only executes from a *dedicated trusted central GitHub workflow*. All meeting
content, the 43-character recovery code and OAuth credentials remain on the
runner Mac or in the explicitly approved encrypted GCS object. Never print
paths, private IDs, tokens, exceptions or user-controlled meeting metadata.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import secrets
import sqlite3
import subprocess
import sys
from urllib.parse import quote

from local_asr_server.storage.cold_migration import (
    DEFAULT_CATALOG, DEFAULT_SETTINGS, MigrationBlocked,
    _catalog_sidecar_state, _entries, _regular, upload_snapshot,
)
from local_asr_server.storage.config import migration_source_roots, TEST_BUCKET
from local_asr_server.storage.gcs_oauth import (
    GCSDesktopOAuth, OAuthUnavailable, read_desktop_config,
)
from local_asr_server.storage.key_recovery import (
    ArchiveKeyUnavailable, native_macos_keychain,
)

CODE_SERVICE = "com.closedroom.app.gcs.migration.recovery"
CODE_ACCOUNT = "cold-migration-v1"
MIN_BYTES = 7_000_000_000
MIN_RECORDINGS = 150
MIN_TRANSCRIPTS = 80
MIN_RECORDING_FILES = 100
SCRATCH_MARGIN = 512 * 1024 * 1024


def _check_app_closed() -> None:
    for name in ("ClosedRoom", "ClosedRoom Test"):
        result = subprocess.run(
            ["/usr/bin/pgrep", "-x", name], capture_output=True, timeout=3,
            check=False,
        )
        if result.returncode == 0:
            raise MigrationBlocked("CLOSEDROOM_MUST_BE_FULLY_QUIT")
        if result.returncode != 1:
            raise MigrationBlocked("PROCESS_CHECK_FAILED")


def preflight() -> dict[str, object]:
    # Never run a personal-data transfer from an arbitrary GitHub-hosted
    # machine, unknown local user or a generic central CI validation lane.
    # A dedicated central CI job may run directly only if its Keychain is
    # accessible. A separately installed *user login-session* LaunchAgent may
    # run the same pinned entrypoint without inheriting CI's Keychain denial.
    from_login_broker = os.environ.get("CLOSEDROOM_TRUSTED_LOGIN_BROKER") == "1"
    from_dedicated_ci = (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_NAME", "").startswith("local-mac-mini-")
    )
    if sys.platform != "darwin" or not (from_login_broker or from_dedicated_ci):
        raise MigrationBlocked("UNAPPROVED_RUNNER_HOST")
    _check_app_closed()

    home = Path.home()
    client_json = home / ".config/closedroom/oauth-desktop.json"
    receipt = home / ".config/closedroom/cold-migration-receipt.json"
    recovery = home / ".config/closedroom/cold-migration-recovery.json"
    work = home / "ClosedRoom-Migration-Work"
    if receipt.exists() or receipt.is_symlink() or recovery.exists() or recovery.is_symlink():
        raise MigrationBlocked("OUTPUT_ALREADY_EXISTS")
    if not receipt.parent.is_dir() or receipt.parent.is_symlink():
        raise MigrationBlocked("PRIVATE_RECEIPT_DIRECTORY_MISSING")
    if work.exists() and (not work.is_dir() or work.is_symlink()):
        raise MigrationBlocked("SCRATCH_DIRECTORY_INVALID")
    if not work.exists():
        work.mkdir(mode=0o700)
    if work.stat().st_mode & 0o077:
        raise MigrationBlocked("SCRATCH_DIRECTORY_NOT_PRIVATE")

    recordings, transcripts = migration_source_roots(DEFAULT_SETTINGS)
    files = _entries(recordings, "recordings") + _entries(transcripts, "transcriptions")
    total_bytes = sum(s.st_size for _, _, s in files)
    if total_bytes < MIN_BYTES or len(files) < MIN_RECORDING_FILES:
        raise MigrationBlocked("EXPECTED_MEETING_DATA_NOT_PRESENT")
    info = _regular(DEFAULT_CATALOG)
    _catalog_sidecar_state(DEFAULT_CATALOG)
    db_uri = "file:" + quote(str(DEFAULT_CATALOG.absolute()), safe="/") + "?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(db_uri, uri=True, timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise MigrationBlocked("CATALOG_INTEGRITY_FAILED")
            recordings_count = db.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
            transcriptions_count = db.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
    except sqlite3.Error:
        raise MigrationBlocked("CATALOG_READ_FAILED") from None
    if recordings_count < MIN_RECORDINGS or transcriptions_count < MIN_TRANSCRIPTS:
        raise MigrationBlocked("EXPECTED_CATALOG_NOT_PRESENT")
    if shutil.disk_usage(work).free < 2 * (total_bytes + info.st_size) + SCRATCH_MARGIN:
        raise MigrationBlocked("INSUFFICIENT_SCRATCH_DISK")

    client_id, client_secret = read_desktop_config(client_json)
    if not GCSDesktopOAuth(client_id=client_id, client_secret=client_secret).is_connected():
        raise MigrationBlocked("MAC_USER_OAUTH_NOT_CONNECTED")
    backend = native_macos_keychain()
    try:
        if backend.get_password(CODE_SERVICE, CODE_ACCOUNT) is not None:
            raise MigrationBlocked("RECOVERY_CODE_ALREADY_STORED")
        # A failed post-upload Keychain write would strand the new archive's
        # portable recovery code. Prove the login process can write, read and
        # delete a *synthetic* secret before uploading a single meeting byte.
        test_account = "preflight-" + secrets.token_hex(16)
        test_secret = secrets.token_urlsafe(32)
        backend.set_password(CODE_SERVICE, test_account, test_secret)
        try:
            if backend.get_password(CODE_SERVICE, test_account) != test_secret:
                raise MigrationBlocked("RECOVERY_KEYCHAIN_NOT_WRITABLE")
        finally:
            backend.delete_password(CODE_SERVICE, test_account)
        if backend.get_password(CODE_SERVICE, test_account) is not None:
            raise MigrationBlocked("RECOVERY_KEYCHAIN_DELETE_FAILED")
    except MigrationBlocked:
        raise
    except Exception:
        raise MigrationBlocked("RECOVERY_KEYCHAIN_NOT_WRITABLE") from None

    return {
        "status": "mac_new_local_backup_preflight_pass",
        "recordings_rows": recordings_count,
        "transcriptions_rows": transcriptions_count,
        "meeting_files": len(files),
        "meeting_bytes": total_bytes,
        "bucket": TEST_BUCKET,
        "cloud_upload_performed": False,
        "secrets_logged": False,
    }


def perform_backup() -> dict[str, object]:
    checked = preflight()
    home = Path.home()
    results, code = upload_snapshot(
        client_json=home / ".config/closedroom/oauth-desktop.json",
        settings_file=DEFAULT_SETTINGS,
        catalog=DEFAULT_CATALOG,
        work_dir=home / "ClosedRoom-Migration-Work",
        receipt=home / ".config/closedroom/cold-migration-receipt.json",
        recovery_file=home / ".config/closedroom/cold-migration-recovery.json",
    )
    # No recovery code may reach GitHub Action output, step output,
    # artifacts or repository commits. Persist it only in native Mac Keychain.
    backend = native_macos_keychain()
    if backend.get_password(CODE_SERVICE, CODE_ACCOUNT) is not None:
        raise MigrationBlocked("RECOVERY_KEYCHAIN_CONFLICT")
    backend.set_password(CODE_SERVICE, CODE_ACCOUNT, code)
    if backend.get_password(CODE_SERVICE, CODE_ACCOUNT) != code:
        raise MigrationBlocked("RECOVERY_KEYCHAIN_SAVE_FAILED")
    return {
        "status": results["status"],
        "bucket": TEST_BUCKET,
        "file_count": results["file_count"],
        "receipt_stored_locally": True,
        "recovery_file_stored_locally": True,
        "recovery_code_stored_in_native_keychain": True,
        "cloud_upload_performed": True,
        "originals_deleted": False,
        "remote_restore_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "backup"))
    args = parser.parse_args(argv)
    try:
        result = preflight() if args.action == "preflight" else perform_backup()
        print(json.dumps(result, sort_keys=True))
        return 0
    except MigrationBlocked as exc:
        error = str(exc)
    except OAuthUnavailable as exc:
        error = exc.code
    except ArchiveKeyUnavailable:
        error = "NATIVE_KEYCHAIN_UNAVAILABLE"
    except Exception:
        # SDK / OS error text can contain credentials, paths, meeting data.
        error = "RUNNER_BACKUP_FAILED_CHECK_LOCAL_PRIVATE_LOGS"
    print(json.dumps({"status": "blocked", "error_code": error},
                     sort_keys=True), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
