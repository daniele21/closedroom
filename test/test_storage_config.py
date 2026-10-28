"""GCS configuration is preparation-only: no upload, no cloud fallback."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_asr_server.storage.config import (  # noqa: E402
    validate_storage_configuration, public_storage_state,
)


class StorageConfigTests(unittest.TestCase):
    def test_local_default_and_staged_coordinates_do_not_enable_cloud(self):
        empty = {"storage_mode": "local", "gcs_project_id": "",
                 "gcs_bucket_name": "", "gcs_region": "europe-west8"}
        validate_storage_configuration(empty)
        self.assertEqual(public_storage_state(empty)["storage_effective_mode"], "local")
        self.assertFalse(public_storage_state(empty)["gcs_configuration_complete"])
        staged = dict(empty, gcs_project_id="project-tests-498508",
                      gcs_bucket_name="project-tests-498508-closedroom-test")
        validate_storage_configuration(staged)
        state = public_storage_state(staged)
        self.assertTrue(state["gcs_configuration_complete"])
        self.assertEqual(state["storage_capability"], "preparation_only")
        self.assertEqual(state["storage_effective_mode"], "local")

    def test_cloud_mode_rejected_even_with_valid_coordinates(self):
        staged = {"storage_mode": "gcs", "gcs_project_id": "project-tests-498508",
                  "gcs_bucket_name": "project-tests-498508-closedroom-test",
                  "gcs_region": "europe-west8"}
        with self.assertRaises(ValueError):
            validate_storage_configuration(staged)
        self.assertEqual(public_storage_state(staged)["storage_effective_mode"], "local")

    def test_invalid_project_bucket_region_and_credentials_rejected(self):
        base = {"storage_mode": "local", "gcs_project_id": "project-tests-498508",
                "gcs_bucket_name": "project-tests-498508-closedroom-test",
                "gcs_region": "europe-west8"}
        invalid = (
            ("gcs_project_id", "../private"),
            ("gcs_project_id", "https://project-tests-498508"),
            ("gcs_bucket_name", "gs://bucket"),
            ("gcs_bucket_name", "https://example.com/"),
            ("gcs_bucket_name", "127.0.0.1"),
            ("gcs_bucket_name", "goog-restricted"),
            ("gcs_region", "../europe-west8"),
            ("gcs_region", ""),
            ("gcs_region", 7),
            ("storage_mode", "remote_or_local"),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    validate_storage_configuration({**base, key: value})


if __name__ == "__main__":
    unittest.main()
