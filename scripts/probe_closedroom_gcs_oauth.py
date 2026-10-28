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

from local_asr_server.storage.gcs_oauth import GCSDesktopOAuth, OAuthUnavailable, AUTH_URI, TOKEN_URI
from local_asr_server.storage.key_recovery import ArchiveKeyUnavailable


def read_desktop_config(path: Path) -> tuple[str, str]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 8192:
            raise ValueError("OAuth client file must be regular and private (0600)")
        # File is explicit and contains a public desktop client secret, not a
        # service-account key. Avoid printing its contents on errors.
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if set(document) != {"installed"}:
            raise ValueError("Only a Google OAuth desktop client is supported")
        cfg = document["installed"]
        if cfg.get("auth_uri") != AUTH_URI or cfg.get("token_uri") != TOKEN_URI:
            raise ValueError("OAuth client endpoint mismatch")
        client_id = cfg["client_id"]
        secret = cfg.get("client_secret", "")
        if not isinstance(secret, str):
            raise ValueError("OAuth desktop client must have a string secret")
        return client_id, secret
    except (OSError, ValueError, KeyError, TypeError):
        raise OAuthUnavailable("Invalid or unavailable private OAuth Desktop client JSON") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["connect", "status", "disconnect-local"])
    parser.add_argument("--client-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        client_id, secret = read_desktop_config(args.client_json)
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
    except (OAuthUnavailable, ArchiveKeyUnavailable, ValueError):
        print("Desktop OAuth discovery failed or was refused; inspect the consent setup locally.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
