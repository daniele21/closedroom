"""Synthetic desktop OAuth tests with no browser, GCP or native Keychain."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from local_asr_server.storage.gcs_oauth import (
    GCSDesktopOAuth, OAuthUnavailable, STORAGE_SCOPE, TOKEN_URI,
)


CLIENT_ID = "12345678-closedroom-test.apps.googleusercontent.com"


class FakeBackend:
    def __init__(self):
        self.items = {}
    def set_password(self, service, name, value):
        self.items[(service, name)] = value
    def get_password(self, service, name):
        return self.items.get((service, name))
    def delete_password(self, service, name):
        del self.items[(service, name)]


class FakeCredentials:
    refresh_token = "fake-offline-refresh-token"
    def to_json(self):
        return json.dumps({
            "client_id": CLIENT_ID, "client_secret": "public-client-secret",
            "refresh_token": self.refresh_token, "token_uri": TOKEN_URI,
            "scopes": [STORAGE_SCOPE],
        })


class FakeFlow:
    def __init__(self):
        self.called = False
    def run_local_server(self, **kwargs):
        self.called = True
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 0
        assert kwargs["access_type"] == "offline"
        assert kwargs["prompt"] == "consent"
        return FakeCredentials()


class FakeGoogleCredentials:
    @classmethod
    def from_authorized_user_info(cls, info, scopes):
        assert scopes == [STORAGE_SCOPE]
        return info


class GCSDesktopOAuthTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.oauth = GCSDesktopOAuth(
            client_id=CLIENT_ID, client_secret="public-client-secret", backend=self.backend
        )

    def test_explicit_consent_only_and_keychain_storage(self):
        self.assertFalse(self.oauth.is_connected())
        self.assertFalse(self.backend.items)
        flow = FakeFlow()
        def factory(config, scopes):
            self.assertEqual(scopes, [STORAGE_SCOPE])
            self.assertEqual(config["installed"]["redirect_uris"], ["http://127.0.0.1"])
            return flow
        with patch("local_asr_server.storage.gcs_oauth.sys.platform", "darwin"):
            self.oauth.authorize_explicitly(flow_factory=factory)
        self.assertTrue(flow.called)
        self.assertTrue(self.oauth.is_connected())
        self.assertEqual(len(self.backend.items), 1)
        self.assertNotIn("test-user@gmail.com", str(self.backend.items.keys()))
        credentials = self.oauth.credentials(credentials_class=FakeGoogleCredentials)
        self.assertEqual(credentials["refresh_token"], FakeCredentials.refresh_token)
        self.oauth.disconnect_local()
        self.assertFalse(self.oauth.is_connected())

    def test_no_browser_on_unsupported_platform(self):
        with patch("local_asr_server.storage.gcs_oauth.sys.platform", "linux"):
            with self.assertRaises(OAuthUnavailable):
                self.oauth.authorize_explicitly(flow_factory=lambda *a, **kw: None)
        self.assertFalse(self.backend.items)

    def test_missing_refresh_token_rejected_before_persist(self):
        class WithoutRefresh(FakeCredentials):
            refresh_token = None
            def to_json(self):
                return json.dumps({
                    "client_id": CLIENT_ID, "token_uri": TOKEN_URI, "scopes": [STORAGE_SCOPE],
                })
        class Flow(FakeFlow):
            def run_local_server(self, **kwargs):
                return WithoutRefresh()
        with patch("local_asr_server.storage.gcs_oauth.sys.platform", "darwin"):
            with self.assertRaises(OAuthUnavailable):
                self.oauth.authorize_explicitly(flow_factory=lambda *a, **kw: Flow())
        self.assertFalse(self.backend.items)

    def test_invalid_credentials_and_broad_scope_fail_closed(self):
        for credentials in (
            {"client_id": CLIENT_ID, "token_uri": TOKEN_URI, "refresh_token": "abc",
             "scopes": ["https://www.googleapis.com/auth/cloud-platform"]},
            {"client_id": CLIENT_ID, "token_uri": TOKEN_URI, "refresh_token": "abc",
             "scopes": [STORAGE_SCOPE, "https://www.googleapis.com/auth/cloud-platform"]},
            {"client_id": "other-client", "token_uri": TOKEN_URI, "refresh_token": "abc",
             "scopes": [STORAGE_SCOPE]},
            {"client_id": CLIENT_ID, "token_uri": "https://evil.test", "refresh_token": "abc",
             "scopes": [STORAGE_SCOPE]},
        ):
            with self.subTest(credentials=credentials):
                self.backend.items = {("com.closedroom.app.gcs.oauth", self.oauth._account): json.dumps(credentials)}
                with self.assertRaises(OAuthUnavailable):
                    self.oauth.credentials(credentials_class=FakeGoogleCredentials)

    def test_invalid_client_id_is_not_loaded(self):
        with self.assertRaises(ValueError):
            GCSDesktopOAuth(client_id="bad", client_secret="", backend=self.backend)


if __name__ == "__main__":
    unittest.main()
