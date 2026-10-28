#!/usr/bin/env python3
"""Explicit desktop OAuth discovery only, isolated from meeting workflows.

Requires a Google OAuth "Desktop app" client JSON configured in GCP.
Never use gcloud ADC, service-account JSON or implicit network fallback.
No recording content is accessed or sent. A local credential in Keychain is
not proof that the Google account currently has bucket IAM.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys

from local_asr_server.storage.gcs_oauth import (
    GCSDesktopOAuth, OAuthUnavailable, CLIENT_ID_RE,
    SUPPORTED_AUTH_URIS, SUPPORTED_TOKEN_URIS,
)
from local_asr_server.storage.key_recovery import ArchiveKeyUnavailable


def read_desktop_config(path: Path) -> tuple[str, str]:
    """Strict local config check with non-secret, actionable error categories."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise OAuthUnavailable(
            "OAuth Desktop JSON not found at the supplied path",
            code="CLIENT_FILE_MISSING",
        ) from None
    except OSError:
        raise OAuthUnavailable("OAuth Desktop JSON cannot be accessed", code="CLIENT_FILE_UNREADABLE") from None

    if not stat.S_ISREG(info.st_mode):
        raise OAuthUnavailable("OAuth Desktop JSON must be a regular file, not a symlink",
                               code="CLIENT_FILE_TYPE")
    if info.st_mode & 0o077:
        raise OAuthUnavailable("OAuth Desktop JSON must have private permissions (chmod 600)",
                               code="CLIENT_FILE_PERMISSIONS")
    if not 0 < info.st_size <= 8192:
        raise OAuthUnavailable("OAuth Desktop JSON is empty or too large", code="CLIENT_FILE_INVALID")
    try:
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, UnicodeError, ValueError):
        raise OAuthUnavailable("OAuth Desktop JSON is unreadable or malformed",
                               code="CLIENT_FILE_INVALID") from None

    if not isinstance(document, dict) or set(document) != {"installed"}:
        raise OAuthUnavailable("Use Google OAuth client type 'Desktop app' (installed)",
                               code="CLIENT_FILE_NOT_DESKTOP")
    cfg = document["installed"]
    if not isinstance(cfg, dict):
        raise OAuthUnavailable("OAuth installed configuration is invalid",
                               code="CLIENT_FILE_INVALID")
    # Exact official Google endpoints only. Google may export the legacy
    # authorization URL, which remains supported; the runtime normalizes it.
    auth_uri, token_uri = cfg.get("auth_uri"), cfg.get("token_uri")
    if (
        not isinstance(auth_uri, str) or auth_uri not in SUPPORTED_AUTH_URIS
        or not isinstance(token_uri, str) or token_uri not in SUPPORTED_TOKEN_URIS
    ):
        raise OAuthUnavailable("OAuth Desktop JSON contains unsupported endpoints",
                               code="CLIENT_ENDPOINT_UNSUPPORTED")
    client_id = cfg.get("client_id")
    if not isinstance(client_id, str) or not CLIENT_ID_RE.fullmatch(client_id):
        raise OAuthUnavailable("OAuth Desktop JSON has an invalid client ID",
                               code="CLIENT_ID_INVALID")
    secret = cfg.get("client_secret", "")
    if not isinstance(secret, str):
        raise OAuthUnavailable("OAuth Desktop client secret field is invalid",
                               code="CLIENT_FILE_INVALID")
    return client_id, secret


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["check-client", "connect", "status", "disconnect-local"])
    parser.add_argument("--client-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        client_id, secret = read_desktop_config(args.client_json)
        if args.operation == "check-client":
            # No Keychain, browser or GCP connection. Never display client ID.
            print(json.dumps({"status": "desktop_client_verified",
                              "network_access": False,
                              "keychain_access": False}, sort_keys=True))
            return 0
        oauth = GCSDesktopOAuth(client_id=client_id, client_secret=secret)
        if args.operation == "connect":
            oauth.authorize_explicitly()
            print(json.dumps({"status": "desktop_oauth_saved_in_keychain",
                              "scope": "devstorage.read_write",
                              "bucket_access_verified": False}))
        elif args.operation == "status":
            print(json.dumps({"status": "local_credentials_present" if oauth.is_connected()
                              else "local_credentials_absent",
                              "bucket_access_verified": False}))
        else:
            oauth.disconnect_local()
            print(json.dumps({"status": "local_credentials_removed",
                              "remote_google_grant_revoked": False}))
        return 0
    except OAuthUnavailable as exc:
        print(json.dumps({"status": "failed", "error_code": exc.code,
                          "message": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    except ArchiveKeyUnavailable:
        print(json.dumps({"status": "failed", "error_code": "KEYCHAIN_UNAVAILABLE",
                          "message": "Native macOS Keychain could not be opened"},
                         sort_keys=True), file=sys.stderr)
        return 2
    except ValueError:
        print(json.dumps({"status": "failed", "error_code": "CLIENT_CONFIG_INVALID",
                          "message": "OAuth Desktop client configuration is invalid"},
                         sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
