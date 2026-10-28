"""Explicit installed-desktop Google OAuth for ClosedRoom GCS archive access.

NEVER use ADC/gcloud/service-account JSON or hidden cloud fallback. Not called
by recording workflows: a separate user-triggered connection UI is required.
OAuth tokens and the archive encryption key are stored in different Keychain
records, and never in settings.json or ordinary log output.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any

from local_asr_server.storage.key_recovery import native_macos_keychain, ArchiveKeyUnavailable

STORAGE_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_SERVICE = "com.closedroom.app.gcs.oauth"
CLIENT_ID_RE = re.compile(r"[0-9]+-[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com\Z")


class OAuthUnavailable(RuntimeError):
    """Desktop consent is unavailable or has not yet been granted."""


def _token_info(value: str, client_id: str) -> dict[str, Any]:
    try:
        info = json.loads(value)
    except (TypeError, ValueError):
        raise OAuthUnavailable("Stored OAuth credential is invalid") from None
    if not isinstance(info, dict) or info.get("client_id") != client_id or (
        info.get("token_uri") != TOKEN_URI
    ) or not isinstance(info.get("refresh_token"), str) or not info["refresh_token"]:
        raise OAuthUnavailable("Stored OAuth credential is incomplete or mismatched")
    scopes = info.get("scopes")
    if not isinstance(scopes, list) or scopes != [STORAGE_SCOPE]:
        raise OAuthUnavailable("GCS OAuth scope was not granted")
    return info


class GCSDesktopOAuth:
    """Own one desktop OAuth client's Keychain credential; no implicit consent."""
    def __init__(self, *, client_id: str, client_secret: str, backend: Any = None):
        if not CLIENT_ID_RE.fullmatch(client_id):
            raise ValueError("Invalid Google Desktop OAuth client ID")
        if not isinstance(client_secret, str):
            raise ValueError("OAuth public installed-app client configuration invalid")
        self._client_id = client_id
        self._client_secret = client_secret
        self._keychain = backend if backend is not None else native_macos_keychain()
        # Opaque account identifier; no email or bearer token in key name.
        self._account = hashlib.sha256(client_id.encode("ascii")).hexdigest()

    def _read(self) -> str | None:
        try:
            return self._keychain.get_password(OAUTH_SERVICE, self._account)
        except Exception:
            raise OAuthUnavailable("Cannot access macOS Keychain for OAuth") from None

    def is_connected(self) -> bool:
        item = self._read()
        if item is None:
            return False
        _token_info(item, self._client_id)
        return True

    def authorize_explicitly(self, *, flow_factory: Any = None) -> None:
        """User-initiated browser authorization with loopback callback/PKCE.

        Real installed-client OAuth configuration must be provisioned through
        the GCP consent screen and must be verified for product distribution.
        The caller must never invoke this during app startup or capture.
        """
        if sys.platform != "darwin":
            raise OAuthUnavailable("Google desktop consent is only available on the Mac")
        if flow_factory is None:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow_factory = InstalledAppFlow.from_client_config
            except ImportError:
                raise OAuthUnavailable("google-auth-oauthlib is required for desktop consent") from None
        cfg = {"installed": {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": ["http://127.0.0.1"],
        }}
        flow = flow_factory(cfg, scopes=[STORAGE_SCOPE])
        # Never use a console code pasted into terminal or a remote redirect.
        creds = flow.run_local_server(
            host="127.0.0.1", port=0, open_browser=True,
            authorization_prompt_message=None,
            success_message="ClosedRoom GCS authorization completed. You may close this window.",
            access_type="offline", prompt="consent",
        )
        if not getattr(creds, "refresh_token", None):
            raise OAuthUnavailable("Google did not return an offline refresh token")
        serialized = creds.to_json()
        _token_info(serialized, self._client_id)
        try:
            self._keychain.set_password(OAUTH_SERVICE, self._account, serialized)
        except Exception:
            raise OAuthUnavailable("Cannot store OAuth credential in macOS Keychain") from None

    def credentials(self, *, credentials_class: Any = None) -> Any:
        """Load OAuth credentials only when a GCS operation is explicitly requested.

        The SDK refreshes expired tokens; refresh token remains in Keychain.
        Application wiring must persist rotated tokens securely if changed.
        """
        item = self._read()
        if item is None:
            raise OAuthUnavailable("Google Cloud Storage is not connected")
        info = _token_info(item, self._client_id)
        if credentials_class is None:
            try:
                from google.oauth2.credentials import Credentials
                credentials_class = Credentials
            except ImportError:
                raise OAuthUnavailable("google-auth is required for GCS credentials") from None
        return credentials_class.from_authorized_user_info(info, scopes=[STORAGE_SCOPE])

    def disconnect_local(self) -> None:
        """Remove the local Keychain grant; not remote Google token revocation."""
        if self._read() is None:
            return
        try:
            self._keychain.delete_password(OAUTH_SERVICE, self._account)
        except Exception:
            raise OAuthUnavailable("Cannot delete local Google OAuth credential") from None
        if self._read() is not None:
            raise OAuthUnavailable("Google OAuth Keychain deletion not verified")
