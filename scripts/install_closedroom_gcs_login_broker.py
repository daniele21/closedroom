#!/usr/bin/env python3
"""Operator-controlled, opt-in installation of the ClosedRoom GCS login LaunchAgent.

Run interactively on the Mac owning the recordings, never inside GitHub CI.
Only pre-authorized source-pinned local requests are accepted. No credentials
or recovery codes are copied into this agent's plist or request inbox.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys

LABEL = "com.closedroom.gcs-login-broker"
SCHEMA = "closedroom-local-gcs-broker-v1"
DEFAULT_SOURCE = Path.home() / "Projects/local-asr-server"
BASE = Path.home() / ".config/closedroom/gcs-login-broker"
PLIST = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
PINNED_BROKER = "scripts/closedroom_gcs_login_broker.py"


def _run(cmd: list[str], *, timeout: int = 12) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def _regular_directory(path: Path, *, private: bool = False) -> None:
    st = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise RuntimeError("INSTALL_DIRECTORY_INVALID")
    if private and st.st_mode & 0o077:
        raise RuntimeError("INSTALL_DIRECTORY_NOT_PRIVATE")


def _write_private_exclusive(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def validate_source(path: Path) -> tuple[str, Path]:
    _regular_directory(path)
    if path != DEFAULT_SOURCE:
        raise RuntimeError("EXPECTED_PROJECTS_SOURCE_REQUIRED")
    head = _run(["/usr/bin/git", "-C", str(path), "rev-parse", "HEAD"])
    if head.returncode:
        raise RuntimeError("SOURCE_GIT_UNAVAILABLE")
    sha = head.stdout.decode("ascii", "replace").strip()
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise RuntimeError("SOURCE_SHA_INVALID")
    dirty = _run(["/usr/bin/git", "-C", str(path), "diff", "--quiet",
                  "--", "scripts", "src/local_asr_server/storage"])
    if dirty.returncode:
        raise RuntimeError("SOURCE_CODE_HAS_LOCAL_CHANGES")
    if not (path / PINNED_BROKER).is_file():
        raise RuntimeError("BROKER_SOURCE_NOT_FOUND")
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("UV_NOT_FOUND")
    uv_path = Path(uv).resolve()
    if not uv_path.is_file():
        raise RuntimeError("UV_NOT_EXECUTABLE")
    return sha, uv_path


def install() -> None:
    if sys.platform != "darwin" or os.environ.get("GITHUB_ACTIONS") == "true":
        raise RuntimeError("INSTALL_FROM_INTERACTIVE_MAC_ONLY")
    source = DEFAULT_SOURCE
    head, uv = validate_source(source)
    if PLIST.exists() or PLIST.is_symlink() or (BASE / "config.json").exists():
        raise RuntimeError("BROKER_ALREADY_INSTALLED")
    _regular_directory(PLIST.parent)
    for parent in (Path.home() / ".config", Path.home() / ".config/closedroom"):
        _regular_directory(parent)
    if not BASE.exists():
        BASE.mkdir(mode=0o700)
    _regular_directory(BASE, private=True)
    if any((BASE / child).exists() for child in ("request.json", "processing.json", "result.json")):
        raise RuntimeError("BROKER_HAS_PENDING_REQUEST")
    config = {
        "schema": SCHEMA,
        "source_sha": head,
        "source_root": str(source),
        "uv_path": str(uv),
    }
    plist = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-P", str(source / PINNED_BROKER)],
        "RunAtLoad": True,
        "WatchPaths": [str(BASE)],
        "ProcessType": "Background",
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "EnvironmentVariables": {"CLOSEDROOM_TRUSTED_LOGIN_BROKER": "1"},
    }
    _write_private_exclusive(BASE / "config.json", (json.dumps(config, sort_keys=True) + "\n").encode())
    try:
        _write_private_exclusive(PLIST, plistlib.dumps(plist, sort_keys=True))
        domain = f"gui/{os.getuid()}"
        started = _run(["/bin/launchctl", "bootstrap", domain, str(PLIST)])
        if started.returncode:
            raise RuntimeError("LAUNCHAGENT_BOOTSTRAP_FAILED")
        print(json.dumps({
            "status": "closedroom_login_gcs_broker_installed",
            "source_sha": head,
            "mac_user_session": True,
            "credential_transfer_to_github": False,
            "backup_started": False,
        }, sort_keys=True))
    except BaseException:
        PLIST.unlink(missing_ok=True)
        (BASE / "config.json").unlink(missing_ok=True)
        raise


def uninstall() -> None:
    if sys.platform != "darwin" or os.environ.get("GITHUB_ACTIONS") == "true":
        raise RuntimeError("UNINSTALL_FROM_INTERACTIVE_MAC_ONLY")
    if (BASE / "processing.json").exists():
        raise RuntimeError("BACKUP_PROCESSING_CANNOT_UNINSTALL")
    domain = f"gui/{os.getuid()}/{LABEL}"
    # Stop the user-session broker, but do not touch meeting files, GCS,
    # OAuth credentials, private receipt, recovery envelope or archive key.
    _run(["/bin/launchctl", "bootout", domain])
    PLIST.unlink(missing_ok=True)
    (BASE / "config.json").unlink(missing_ok=True)
    print(json.dumps({"status": "closedroom_login_gcs_broker_uninstalled",
                      "meeting_data_deleted": False, "credentials_revoked": False,
                      "recovery_files_deleted": False}, sort_keys=True))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("install", "uninstall"))
    args = p.parse_args()
    try:
        install() if args.action == "install" else uninstall()
        return 0
    except Exception as exc:
        code = str(exc)
        if not re.fullmatch(r"[A-Z_]{5,80}", code):
            code = "BROKER_INSTALL_FAILED"
        print(json.dumps({"status": "blocked", "error_code": code}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
