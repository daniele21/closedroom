"""Dev source launch must never write the installed ClosedRoom profile."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.catalog import CatalogStore
from local_asr_server.paths import (
    get_app_support_dir, get_logs_dir, get_runtime_state_file,
    get_settings_file, is_development_profile,
)
from local_asr_server.settings import (
    load_settings, save_settings, validate_development_storage,
)


class DevelopmentProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"CLOSEDROOM_DEV_PROFILE": "1"})
        self.home = patch("local_asr_server.paths.Path.home", return_value=self.root)
        self.env.start()
        self.home.start()

    def tearDown(self):
        self.home.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_production_and_dev_settings_runtime_and_logs_are_distinct(self):
        self.assertTrue(is_development_profile())
        support = get_app_support_dir()
        self.assertEqual(support, self.root / "Library/Application Support/ClosedRoom/Development")
        self.assertEqual(get_settings_file(), support / "settings.json")
        self.assertEqual(get_runtime_state_file(), support / "runtime-state.json")
        self.assertEqual(get_logs_dir(), self.root / "Library/Logs/ClosedRoom/Development")

        with patch.dict(os.environ, {"CLOSEDROOM_DEV_PROFILE": "0"}):
            self.assertEqual(
                get_settings_file(),
                self.root / "Library/Application Support/ClosedRoom/settings.json",
            )
            self.assertEqual(
                get_runtime_state_file(),
                self.root / "Library/Application Support/ClosedRoom/runtime-state.json",
            )

    def test_dev_defaults_use_isolated_recordings_transcriptions_and_catalog(self):
        defaults = load_settings()
        root = get_app_support_dir() / "Data"
        for key in ("recordings_dir", "transcriptions_dir", "catalog_db_path"):
            self.assertIn(root.resolve(), Path(defaults[key]).resolve().parents)
        self.assertEqual(Path(defaults["catalog_db_path"]), root / "closedroom.db")

    def test_legacy_production_catalog_cannot_be_autodiscovered(self):
        production_db = self.root / "ClosedRoom" / "closedroom.db"
        production_db.parent.mkdir(parents=True)
        production_db.write_bytes(b"PRODUCTION DATA")
        actual = CatalogStore.default_db_path()
        self.assertNotEqual(actual, production_db)
        self.assertEqual(actual, (get_app_support_dir() / "Data/closedroom.db").resolve())
        self.assertEqual(production_db.read_bytes(), b"PRODUCTION DATA")

    def test_persisted_dev_settings_cannot_point_back_to_production(self):
        dev_settings = load_settings()
        dev_settings["recordings_dir"] = str(self.root / "ClosedRoom/Recordings/ClosedRoom")
        with self.assertRaisesRegex(ValueError, "installed app"):
            save_settings(dev_settings)
        self.assertFalse(get_settings_file().exists())

        # Tampered or legacy unsafe settings must fail closed upon loading.
        get_settings_file().write_text(json.dumps(dev_settings), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "installed app"):
            load_settings()

    def test_catalog_and_explicit_recording_overrides_cannot_escape_sandbox(self):
        safe = load_settings()
        bad = self.root / "ClosedRoom" / "closedroom.db"
        with self.assertRaisesRegex(ValueError, "installed app"):
            validate_development_storage(safe, catalog_db=bad)
        with self.assertRaisesRegex(ValueError, "installed app"):
            validate_development_storage(safe, recordings_dir=self.root / "Meetings")
        with patch.dict(os.environ, {"CLOSEDROOM_CATALOG_DB": str(bad)}):
            with self.assertRaisesRegex(ValueError, "installed app"):
                CatalogStore.default_db_path()

    def test_symlink_to_production_storage_is_rejected(self):
        prod = self.root / "ClosedRoom" / "Recordings"
        prod.mkdir(parents=True)
        link = get_app_support_dir() / "Data" / "Remote"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(prod, target_is_directory=True)
        bad = {**load_settings(), "recordings_dir": str(link)}
        with self.assertRaisesRegex(ValueError, "installed app"):
            save_settings(bad)

    def test_valid_development_save_does_not_touch_production_preferences(self):
        production = self.root / "Library/Application Support/ClosedRoom/settings.json"
        production.parent.mkdir(parents=True)
        production.write_text('{"meeting_detection_enabled": false}', encoding="utf-8")
        dev_settings = load_settings()
        dev_settings["meeting_detection_enabled"] = True
        save_settings(dev_settings)
        self.assertTrue(load_settings()["meeting_detection_enabled"])
        self.assertEqual(production.read_text(encoding="utf-8"),
                         '{"meeting_detection_enabled": false}')


if __name__ == "__main__":
    unittest.main()
