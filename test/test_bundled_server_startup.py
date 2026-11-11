"""Regression for installed-app startup without the isolated development profile.

These tests must never inspect or write the user's real ClosedRoom catalog.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from local_asr_server.app_services import get_services
from local_asr_server.server import create_app
from support import deterministic_settings


class BundledServerStartupTests(unittest.TestCase):
    def test_non_development_server_starts_from_saved_recording_settings(self) -> None:
        """Exercise the same create_app(recordings_dir=None) entry used by the .app."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = deterministic_settings(
                root,
                recordings_dir=str(root / "user-configured-recordings"),
                catalog_db_path=str(root / "catalog.db"),
            )
            (root / "static").mkdir()
            # All persistence owners resolve into the test root. There is no
            # access to ~/ClosedRoom, nor a simulated production-data migration.
            with (
                patch.dict(os.environ, {
                    "CLOSEDROOM_DEV_PROFILE": "0",
                    "CLOSEDROOM_RECORDINGS_DIR": "",
                    "CLOSEDROOM_CATALOG_DB": "",
                }),
                patch("local_asr_server.settings.load_settings", return_value=paths),
                patch("local_asr_server.catalog.load_settings", return_value=paths),
                patch("local_asr_server.transcriptions.load_settings", return_value=paths),
                patch("local_asr_server.server.get_static_dir", return_value=root / "static"),
                patch("local_asr_server.server.configure_application_logging",
                      return_value=str(root / "closedroom.log")),
            ):
                app = create_app(
                    default_model="test-model", recordings_dir=None, enable_auth=False,
                )
                services = get_services(app)
                self.assertEqual(
                    services.recordings.root, (root / "user-configured-recordings").resolve(),
                )
                self.assertTrue(services.catalog.db_path.resolve().is_relative_to(root.resolve()))
                self.assertTrue(
                    services.transcriptions.root.resolve().is_relative_to(root.resolve())
                )
                with TestClient(app) as client:
                    health = client.get("/health")
                    self.assertEqual(health.status_code, 200, health.text)
                    self.assertTrue(health.json()["ok"])
                    self.assertEqual(health.json()["server"], "local-asr-server")
                # The installed profile may invoke the shared storage validator;
                # it must nevertheless initialize and serve the configured data.
                # The separate dev-profile test below checks the fail-closed guard.

    def test_development_storage_is_still_rejected_before_store_creation(self) -> None:
        """Moving the import must not relax the dev/installed-data boundary."""
        with (
            patch.dict(os.environ, {"CLOSEDROOM_DEV_PROFILE": "1",
                                    "CLOSEDROOM_RECORDINGS_DIR": ""}),
            patch("local_asr_server.settings.load_settings",
                  return_value={"recordings_dir": "/unsafe"}),
            patch("local_asr_server.settings.validate_development_storage",
                  side_effect=ValueError("development storage boundary")) as validate,
            patch("local_asr_server.server.CatalogStore") as catalog,
        ):
            with self.assertRaisesRegex(ValueError, "development storage boundary"):
                create_app(default_model="test-model", recordings_dir=None)
            validate.assert_called_once()
            catalog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
