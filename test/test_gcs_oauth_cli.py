"""Desktop OAuth CLI accepts only private Google installed-client config."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.probe_closedroom_gcs_oauth import read_desktop_config
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


if __name__ == '__main__':
    unittest.main()
