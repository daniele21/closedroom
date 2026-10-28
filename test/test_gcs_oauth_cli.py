"""Desktop OAuth CLI accepts only private Google installed-client config."""
from __future__ import annotations

import io
import contextlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.probe_closedroom_gcs_oauth import read_desktop_config, main
from local_asr_server.storage.gcs_oauth import OAuthUnavailable, AUTH_URI, TOKEN_URI


class TestDesktopOAuthConfig(unittest.TestCase):
    def test_private_installed_client_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'client.json'
            f.write_text(json.dumps({'installed': {
                'client_id': '12345678-closedroom-test.apps.googleusercontent.com',
                'client_secret': 'public-desktop-client',
                'auth_uri': AUTH_URI, 'token_uri': TOKEN_URI,
                'redirect_uris': ['http://127.0.0.1'],
            }}))
            f.chmod(0o600)
            self.assertEqual(read_desktop_config(f)[0],
                             '12345678-closedroom-test.apps.googleusercontent.com')

    def test_service_account_and_world_readable_config_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'client.json'
            f.write_text(json.dumps({'type': 'service_account',
                                     'private_key': 'test-not-a-real-key'}))
            f.chmod(0o600)
            with self.assertRaises(OAuthUnavailable):
                read_desktop_config(f)
            f.write_text(json.dumps({'installed': {'auth_uri': AUTH_URI, 'token_uri': TOKEN_URI}}))
            f.chmod(0o644)
            with self.assertRaises(OAuthUnavailable):
                read_desktop_config(f)
            f.chmod(0o600)
            f.write_text(json.dumps({'installed': {'auth_uri': 'https://evil.test',
                                                   'token_uri': TOKEN_URI,
                                                   'client_id': 'unused'}}))
            with self.assertRaises(OAuthUnavailable):
                read_desktop_config(f)


    def test_google_legacy_auth_url_is_accepted(self):
        # Real downloaded Google OAuth Desktop JSON may use this URL.
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "client.json"
            f.write_text(json.dumps({"installed": {
                "client_id": "12345678-test.apps.googleusercontent.com",
                "client_secret": "example",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
                "redirect_uris": ["http://localhost"],
            }}))
            f.chmod(0o600)
            self.assertEqual(read_desktop_config(f)[0], "12345678-test.apps.googleusercontent.com")

    def test_missing_file_diagnostic_without_exposing_path(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "do-not-print-my-path.json"
            with self.assertRaises(OAuthUnavailable) as caught:
                read_desktop_config(missing)
            self.assertEqual(caught.exception.code, "CLIENT_FILE_MISSING")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                exit_code = main(["connect", "--client-json", str(missing)])
            self.assertEqual(exit_code, 2)
            diagnostic = json.loads(err.getvalue())
            self.assertEqual(diagnostic["error_code"], "CLIENT_FILE_MISSING")
            self.assertNotIn("do-not-print-my-path", err.getvalue())

    def test_permissions_and_wrong_client_type_have_distinct_codes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "client.json"
            f.write_text(json.dumps({"installed": {
                "client_id": "12345678-test.apps.googleusercontent.com",
                "auth_uri": AUTH_URI, "token_uri": TOKEN_URI,
            }}))
            f.chmod(0o644)
            with self.assertRaises(OAuthUnavailable) as caught:
                read_desktop_config(f)
            self.assertEqual(caught.exception.code, "CLIENT_FILE_PERMISSIONS")
            f.write_text(json.dumps({"web": {"client_secret": "do-not-print-secret"}}))
            f.chmod(0o600)
            with self.assertRaises(OAuthUnavailable) as caught:
                read_desktop_config(f)
            self.assertEqual(caught.exception.code, "CLIENT_FILE_NOT_DESKTOP")
            self.assertNotIn("do-not-print-secret", str(caught.exception))

    def test_unsupported_third_party_auth_endpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "client.json"
            f.write_text(json.dumps({"installed": {
                "client_id": "12345678-test.apps.googleusercontent.com",
                "auth_uri": "https://oauth.example.test/oauth2",
                "token_uri": TOKEN_URI,
            }}))
            f.chmod(0o600)
            with self.assertRaises(OAuthUnavailable) as caught:
                read_desktop_config(f)
            self.assertEqual(caught.exception.code, "CLIENT_ENDPOINT_UNSUPPORTED")


if __name__ == '__main__':
    unittest.main()
