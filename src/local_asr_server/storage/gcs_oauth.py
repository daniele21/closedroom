"""Explicit installed-desktop Google OAuth for ClosedRoom GCS archive access.

NEVER use ADC/gcloud/service-account JSON or hidden cloud fallback. Not called
by recording workflows: a separate user-triggered connection UI is required.
OAuth tokens and the archive encryption key are stored in different Keychain
records, and never in settings.json or ordinary log output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import re
import sys
from typing import Any

from local_asr_server.storage.key_recovery import native_macos_keychain, ArchiveKeyUnavailable

STORAGE_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
# Google Desktop JSON may contain the older official authorization endpoint.
SUPPORTED_AUTH_URIS = frozenset({AUTH_URI, "https://accounts.google.com/o/oauth2/auth"})
SUPPORTED_TOKEN_URIS = frozenset({TOKEN_URI, "https://accounts.google.com/o/oauth2/token"})
OAUTH_SERVICE = "com.closedroom.app.gcs.oauth"
CLIENT_ID_RE = re.compile(r"[0-9]+-[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com\Z")


class OAuthUnavailable(RuntimeError):
    """Safe diagnostic code; never include OAuth provider exception strings."""

    def __init__(self, message: str, *, code: str = "OAUTH_UNAVAILABLE"):
        super().__init__(message)
        self.code = code


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



def _token_info(value: str, client_id: str) -> dict[str, Any]:
    try:
        info = json.loads(value)
    except (TypeError, ValueError):
        raise OAuthUnavailable("Stored OAuth credential is invalid", code="KEYCHAIN_CREDENTIAL_INVALID") from None
    if not isinstance(info, dict) or info.get("client_id") != client_id or (
        info.get("token_uri") != TOKEN_URI
    ) or not isinstance(info.get("refresh_token"), str) or not info["refresh_token"]:
        raise OAuthUnavailable("Stored OAuth credential is incomplete or mismatched", code="KEYCHAIN_CREDENTIAL_INVALID")
    scopes = info.get("scopes")
    if not isinstance(scopes, list) or scopes != [STORAGE_SCOPE]:
        raise OAuthUnavailable("GCS OAuth scope was not granted", code="OAUTH_SCOPE_MISMATCH")
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
            raise OAuthUnavailable("Cannot access macOS Keychain for OAuth", code="KEYCHAIN_READ_FAILED") from None

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
            raise OAuthUnavailable("Google desktop consent is only available on the Mac", code="PLATFORM_UNSUPPORTED")
        if flow_factory is None:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow_factory = InstalledAppFlow.from_client_config
            except ImportError:
                raise OAuthUnavailable("google-auth-oauthlib is required for desktop consent", code="OAUTH_DEPENDENCY_MISSING") from None
        cfg = {"installed": {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": ["http://127.0.0.1"],
        }}
        try:
            flow = flow_factory(cfg, scopes=[STORAGE_SCOPE])
        except Exception:
            # Underlying provider exceptions may contain sensitive URLs.
            raise OAuthUnavailable("Desktop OAuth flow could not start", code="OAUTH_FLOW_INIT_FAILED") from None
        # Never use a console code pasted into terminal or a remote redirect.
        try:
            creds = flow.run_local_server(
                host="127.0.0.1", port=0, open_browser=True,
                authorization_prompt_message=None,
                success_message="ClosedRoom GCS authorization completed. You may close this window.",
                access_type="offline", prompt="consent",
                timeout_seconds=180,
            )
        except Exception:
            # The browser, consent screen, local callback and token exchange
            # all occur here; do not print an OAuth exception or callback URL.
            raise OAuthUnavailable(
                "Browser consent, loopback callback or token exchange failed",
                code="OAUTH_BROWSER_FLOW_FAILED",
            ) from None
        if not getattr(creds, "refresh_token", None):
            raise OAuthUnavailable("Google did not return an offline refresh token", code="OAUTH_REFRESH_TOKEN_MISSING")
        serialized = creds.to_json()
        _token_info(serialized, self._client_id)
        try:
            self._keychain.set_password(OAUTH_SERVICE, self._account, serialized)
        except Exception:
            raise OAuthUnavailable("Cannot store OAuth credential in macOS Keychain", code="KEYCHAIN_WRITE_FAILED") from None

    def credentials(self, *, credentials_class: Any = None) -> Any:
        """Load OAuth credentials only when a GCS operation is explicitly requested.

        The SDK refreshes expired tokens; refresh token remains in Keychain.
        Application wiring must persist rotated tokens securely if changed.
        """
        item = self._read()
        if item is None:
            raise OAuthUnavailable("Google Cloud Storage is not connected", code="OAUTH_NOT_CONNECTED")
        info = _token_info(item, self._client_id)
        if credentials_class is None:
            try:
                from google.oauth2.credentials import Credentials
                credentials_class = Credentials
            except ImportError:
                raise OAuthUnavailable("google-auth is required for GCS credentials", code="OAUTH_DEPENDENCY_MISSING") from None
        return credentials_class.from_authorized_user_info(info, scopes=[STORAGE_SCOPE])

    def disconnect_local(self) -> None:
        """Remove the local Keychain grant; not remote Google token revocation."""
        if self._read() is None:
            return
        try:
            self._keychain.delete_password(OAUTH_SERVICE, self._account)
        except Exception:
            raise OAuthUnavailable("Cannot delete local Google OAuth credential", code="KEYCHAIN_DELETE_FAILED") from None
        if self._read() is not None:
            raise OAuthUnavailable("Google OAuth Keychain deletion not verified", code="KEYCHAIN_DELETE_FAILED")
