from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.catalog import CatalogStore


class CatalogDefaultDbPathTests(unittest.TestCase):
    def test_prefers_temp_transcriptions_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp).resolve()
            with patch("local_asr_server.catalog.load_settings", return_value={
                "transcriptions_dir": str(temp_path / "transcriptions"),
                "recordings_dir": str(temp_path / "recordings"),
            }):
                resolved = CatalogStore.default_db_path()
                self.assertEqual(resolved, (temp_path / "transcriptions" / "closedroom.db").resolve())

    def test_prefers_temp_recordings_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp).resolve()
            with patch("local_asr_server.catalog.load_settings", return_value={
                "transcriptions_dir": "/non/existent/transcriptions",
                "recordings_dir": str(temp_path / "recordings"),
            }):
                resolved = CatalogStore.default_db_path()
                self.assertEqual(resolved, (temp_path / "recordings" / "closedroom.db").resolve())

    def test_env_var_override(self) -> None:
        target = Path("/tmp/custom_closedroom.db").resolve()
        with patch.dict(os.environ, {"CLOSEDROOM_CATALOG_DB": str(target)}):
            with patch("local_asr_server.catalog.load_settings", return_value={
                "transcriptions_dir": "/var/data/transcriptions",
                "recordings_dir": "/var/data/recordings",
            }):
                resolved = CatalogStore.default_db_path()
                self.assertEqual(resolved, target)

    def test_candidate_workspace_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            workspace = Path(fake_home) / "ClosedRoom"
            workspace.mkdir(parents=True)
            db_file = workspace / "closedroom.db"
            db_file.touch()

            # Mock tempfile.gettempdir so fake_home is not treated as temp_root
            with (
                patch("local_asr_server.catalog.tempfile.gettempdir", return_value="/different/temp/dir"),
                patch("local_asr_server.catalog.Path.home", return_value=Path(fake_home)),
                patch("local_asr_server.catalog.load_settings", return_value={
                    "transcriptions_dir": str(workspace / "Transcriptions" / "ClosedRoom"),
                    "recordings_dir": str(workspace / "Recordings" / "ClosedRoom"),
                }),
            ):
                resolved = CatalogStore.default_db_path()
                self.assertEqual(resolved, db_file.resolve())

    def test_app_support_fallback_when_workspace_missing(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            with (
                patch("local_asr_server.catalog.tempfile.gettempdir", return_value="/different/temp/dir"),
                patch("local_asr_server.catalog.Path.home", return_value=Path(fake_home)),
                patch("local_asr_server.paths.Path.home", return_value=Path(fake_home)),
                patch("local_asr_server.catalog.load_settings", return_value={
                    "transcriptions_dir": "/non/existent/transcriptions",
                    "recordings_dir": "/non/existent/recordings",
                }),
            ):
                resolved = CatalogStore.default_db_path()
                expected = (Path(fake_home) / "Library" / "Application Support" / "ClosedRoom" / "closedroom.db").resolve()
                self.assertEqual(resolved, expected)


if __name__ == "__main__":
    unittest.main()
