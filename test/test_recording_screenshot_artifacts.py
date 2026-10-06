from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from local_asr_server.recording_screenshot_artifacts import (
    SCREENSHOT_MANIFEST_VERSION,
    ScreenshotArtifactStore,
)


class ScreenshotArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.session = Path(self.temp.name)
        self.store = ScreenshotArtifactStore(
            conflict_error=ValueError,
            not_found_error=FileNotFoundError,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_manifest_projects_empty_recording_manifest(self) -> None:
        manifest = self.store.read_manifest(self.session, "rec-1")
        self.assertEqual(manifest["schema_version"], SCREENSHOT_MANIFEST_VERSION)
        self.assertEqual(manifest["recording_id"], "rec-1")
        self.assertEqual(manifest["items"], [])

    def test_public_projection_hides_internal_file_names_and_reports_availability(self) -> None:
        directory = self.store.directory(self.session)
        directory.mkdir()
        (directory / "shot.jpg").write_bytes(b"original")
        (directory / "shot-thumb.jpg").write_bytes(b"thumb")
        projected = self.store.public(
            self.session,
            {
                "screenshot_id": "shot-1",
                "original_file": "shot.jpg",
                "thumbnail_file": "shot-thumb.jpg",
            },
        )
        self.assertTrue(projected["available"])
        self.assertTrue(projected["thumbnail_available"])
        self.assertNotIn("original_file", projected)
        self.assertNotIn("thumbnail_file", projected)

    def test_manifest_validation_fails_closed(self) -> None:
        directory = self.store.directory(self.session)
        directory.mkdir()
        self.store.manifest_path(self.session).write_text(
            json.dumps({"schema_version": 999, "items": []}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Unsupported screenshot manifest version"):
            self.store.read_manifest(self.session, "rec-1")


if __name__ == "__main__":
    unittest.main()
