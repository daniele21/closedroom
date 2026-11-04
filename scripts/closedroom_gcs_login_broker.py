#!/usr/bin/env python3
"""One-shot source-pinned ClosedRoom GCS request executor in a macOS login LaunchAgent.

The central self-hosted runner deposits a *non-secret* request in a private
local inbox. This process alone uses the user's login-session Keychain.
Never print subprocess logs, recovery keys, credentials or meeting metadata.
The agent is inert without an explicit, fresh, allowlisted local request.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

SCHEMA = "closedroom-local-gcs-broker-v1"
BUCKET = "project-tests-498508-closedroom-test"
ACTIONS = ("oauth-verify", "preflight", "backup", "restore-verify")
MAX_AGE_SECONDS = 600
RUN_TIMEOUT_SECONDS = 10800
BROKER_DIR = Path.home() / ".config/closedroom/gcs-login-broker"
CONFIG = BROKER_DIR / "config.json"
REQUEST = BROKER_DIR / "request.json"
PROCESSING = BROKER_DIR / "processing.json"
RESULT = BROKER_DIR / "result.json"
SHA = re.compile(r"[a-f0-9]{40}\Z")
NONCE = re.compile(r"[a-f0-9]{32}\Z")
ERROR = re.compile(r"[A-Z0-9_]{3,80}\Z")


class BrokerRefusal(Exception):
    def __init__(self, code: str):
        self.code = code


def private_regular(path: Path, *, max_bytes: int = 4096) -> bytes:
    try:
        st = path.lstat()
        if (not path.is_file() or path.is_symlink() or st.st_uid != os.getuid()
                or st.st_mode & 0o077 or st.st_size > max_bytes):
            raise BrokerRefusal("PRIVATE_INPUT_INVALID")
        return path.read_bytes()
    except OSError:
        raise BrokerRefusal("PRIVATE_INPUT_MISSING") from None


def read_private_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(private_regular(path))
    except (ValueError, UnicodeDecodeError):
        raise BrokerRefusal("PRIVATE_JSON_INVALID") from None
    if not isinstance(data, dict):
        raise BrokerRefusal("PRIVATE_JSON_INVALID")
    return data


def validate_request(request: dict[str, Any], config: dict[str, Any], now: int) -> None:
    if set(config) != {"schema", "source_sha", "source_root", "uv_path"} or config.get("schema") != SCHEMA:
        raise BrokerRefusal("BROKER_CONFIG_INVALID")
    if not SHA.fullmatch(str(config.get("source_sha", ""))):
        raise BrokerRefusal("BROKER_CONFIG_INVALID")
    if set(request) != {"schema", "nonce", "source_sha", "bucket", "action", "approved", "created_at"}:
        raise BrokerRefusal("REQUEST_INVALID")
    if request["schema"] != SCHEMA or not isinstance(request["nonce"], str) or not NONCE.fullmatch(request["nonce"]):
        raise BrokerRefusal("REQUEST_INVALID")
    if (request["source_sha"] != config["source_sha"] or request["bucket"] != BUCKET
            or request["action"] not in ACTIONS
            or type(request["approved"]) is not bool
            or request["approved"] != (request["action"] == "backup")):
        raise BrokerRefusal("REQUEST_NOT_AUTHORIZED")
    created = request["created_at"]
    if type(created) is not int or created > now + 30 or now - created > MAX_AGE_SECONDS:
        raise BrokerRefusal("REQUEST_EXPIRED")


def _status_from_output(text: str, action: str) -> dict[str, Any]:
    try:
        data = json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise BrokerRefusal("BACKEND_INVALID_RESULT") from None
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        raise BrokerRefusal("BACKEND_INVALID_RESULT")
    status = data["status"]
    if status == "blocked" or status == "failed":
        code = data.get("error_code")
        raise BrokerRefusal(code if isinstance(code, str) and ERROR.fullmatch(code) else "BACKEND_FAILED")
    allowed = {
        "oauth-verify": "oauth_bucket_read_write_verified",
        "preflight": "mac_new_local_backup_preflight_pass",
        "backup": "cold_snapshot_uploaded_pending_restore",
        "restore-verify": "cold_snapshot_restored_verified_isolated",
    }
    if status != allowed[action]:
        raise BrokerRefusal("BACKEND_UNEXPECTED_RESULT")
    result = {"status": status, "action": action}
    for field in ("meeting_bytes", "meeting_files", "recordings_rows", "transcriptions_rows", "file_count", "restored_files"):
        v = data.get(field)
        if type(v) is int and 0 <= v <= 10**14:
            result[field] = v
    if action == "backup" and data.get("recovery_code_stored_in_native_keychain") is not True:
        raise BrokerRefusal("RECOVERY_KEY_NOT_SECURELY_STORED")
    return result


def run_action(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    source = Path(config["source_root"])
    uv = Path(config["uv_path"])
    if (not source.is_absolute() or not source.is_dir() or source.is_symlink()
            or not uv.is_absolute() or not uv.is_file() or uv.is_symlink()):
        raise BrokerRefusal("BROKER_INSTALL_INVALID")
    try:
        head = subprocess.run(["/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"],
                              capture_output=True, check=True, timeout=8)
        if head.stdout.decode().strip() != config["source_sha"]:
            raise BrokerRefusal("BROKER_SOURCE_SHA_CHANGED")
        # Prevent uncommitted source modifications from running in a trusted
        # login process, even if the HEAD commit is the same.
        diff = subprocess.run(["/usr/bin/git", "-C", str(source), "diff", "--quiet",
                               "--", "scripts", "src/local_asr_server/storage"],
                              capture_output=True, timeout=8)
        if diff.returncode != 0:
            raise BrokerRefusal("BROKER_SOURCE_CHANGED")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, UnicodeDecodeError):
        raise BrokerRefusal("BROKER_SOURCE_UNAVAILABLE") from None

    env = {
        **os.environ,
        "PYTHONPATH": "src",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CLOSEDROOM_TRUSTED_LOGIN_BROKER": "1",
    }
    common = [
        str(uv), "run", "--no-project", "--with", "cryptography",
        "--with", "keyring", "--with", "google-auth",
        "--with", "google-auth-oauthlib", "--with", "google-cloud-storage",
        "python", "-P",
    ]
    action = request["action"]
    if action == "oauth-verify":
        cmd = common + [
            "scripts/probe_closedroom_gcs_oauth.py", "verify-bucket",
            "--client-json", str(Path.home() / ".config/closedroom/oauth-desktop.json"),
            "--apply",
        ]
    elif action == "restore-verify":
        # Full encrypted cloud download/decrypt into a private scratch
        # directory in the login session. The existing app data remains
        # untouched; never read the one-time recovery code in CI.
        cmd = common + ["scripts/verify_closedroom_gcs_cold_restore.py"]
    else:
        cmd = common + ["scripts/run_gcs_backup_on_runner.py", action]
    try:
        proc = subprocess.run(cmd, cwd=source, env=env, capture_output=True,
                              timeout=RUN_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise BrokerRefusal("BACKEND_TIMEOUT") from None
    except OSError:
        raise BrokerRefusal("BACKEND_EXECUTION_FAILED") from None
    # Child output must never be relayed verbatim to GitHub Actions: it may
    # include personal paths, SDK exceptions, OAuth tokens or recovery codes.
    if proc.returncode:
        return _status_from_output(proc.stderr.decode("utf-8", "replace"), action)
    return _status_from_output(proc.stdout.decode("utf-8", "replace"), action)


def atomic_private_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(".result-" + os.urandom(8).hex() + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(data, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def poll() -> int:
    if sys.platform != "darwin" or os.environ.get("CLOSEDROOM_TRUSTED_LOGIN_BROKER") != "1":
        return 2
    if BROKER_DIR.is_symlink() or not BROKER_DIR.is_dir():
        return 2
    directory = BROKER_DIR.stat()
    if directory.st_uid != os.getuid() or directory.st_mode & 0o077:
        return 2
    if not REQUEST.is_file() or PROCESSING.exists() or RESULT.exists():
        return 0

    try:
        config = read_private_json(CONFIG)
        request = read_private_json(REQUEST)
        validate_request(request, config, int(time.time()))
        os.replace(REQUEST, PROCESSING)
    except BrokerRefusal:
        # Do not touch requests we have not validated, and never write
        # an uncorrelated result to the runner.
        return 2
    except OSError:
        return 2

    nonce = request["nonce"]
    try:
        result = run_action(request, config)
        output = {"schema": SCHEMA, "nonce": nonce, "ok": True, **result}
    except BrokerRefusal as exc:
        output = {"schema": SCHEMA, "nonce": nonce, "ok": False, "error_code": exc.code}
    except BaseException:
        output = {"schema": SCHEMA, "nonce": nonce, "ok": False, "error_code": "BROKER_INTERNAL_ERROR"}
    try:
        atomic_private_json(RESULT, output)
    except OSError:
        return 2
    finally:
        # A failure writing the result preserves the processing file for
        # forensic review; never automatically replay an expensive backup.
        if RESULT.is_file():
            PROCESSING.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(poll())
