from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.recordings import RecordingStore


JPEG_ORIGINAL = b"\xff\xd8\xff" + (b"original" * 128)
JPEG_THUMBNAIL = b"\xff\xd8\xff" + (b"thumb" * 64)


class ScreenshotCaptureCoreStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = RecordingStore(self.root, use_settings_dir=False)
        self.recording = self.store.create(
            title="Capture Core",
            mime_type="audio/wav",
            model="test",
            language="it",
            capture_mode="both",
            capture_backend="native",
        )
        self.recording_id = self.recording["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _capture(self) -> dict:
        return {
            "display_id": 7,
            "display_title": "Screen 1",
            "captured_uptime": 12.5,
            "captured_wall_time": 1000.0,
            "recording_ready_uptime": 10.0,
            "timestamp": 2.5,
            "width": 1920,
            "height": 1080,
            "thumbnail_width": 640,
            "thumbnail_height": 360,
            "overlay_exclusion": "closedroom_applications",
            "capture_ms": 90,
            "encode_ms": 30,
            "write_ms": 8,
            "roundtrip_ms": 140,
            "worker_restart_count": 0,
        }

    def test_staged_screenshot_is_promoted_without_byte_rewrite(self) -> None:
        staging = self.store.reserve_screenshot_capture(
            self.recording_id,
            request_id="request-1",
        )
        staging["original_path"].write_bytes(JPEG_ORIGINAL)
        staging["thumbnail_path"].write_bytes(JPEG_THUMBNAIL)

        with patch.object(
            self.store,
            "_write_bytes_atomic",
            side_effect=AssertionError("screenshot bytes were rewritten"),
        ):
            saved = self.store.commit_screenshot_capture(
                self.recording_id,
                request_id="request-1",
                token=staging["token"],
                capture=self._capture(),
            )

        self.assertTrue(saved["available"])
        self.assertTrue(saved["thumbnail_available"])
        self.assertEqual(saved["bytes"], len(JPEG_ORIGINAL))
        self.assertEqual(saved["thumbnail_bytes"], len(JPEG_THUMBNAIL))
        self.assertEqual(saved["capture_ms"], 90)
        self.assertEqual(saved["roundtrip_ms"], 140)
        self.assertFalse(staging["original_path"].exists())
        self.assertFalse(staging["thumbnail_path"].exists())

        original = self.store.screenshot_asset_path(
            self.recording_id,
            saved["screenshot_id"],
            thumbnail=False,
        )
        thumbnail = self.store.screenshot_asset_path(
            self.recording_id,
            saved["screenshot_id"],
            thumbnail=True,
        )
        self.assertEqual(original.read_bytes(), JPEG_ORIGINAL)
        self.assertEqual(thumbnail.read_bytes(), JPEG_THUMBNAIL)

    def test_duplicate_request_commits_only_one_asset(self) -> None:
        first = self.store.reserve_screenshot_capture(
            self.recording_id,
            request_id="same-request",
        )
        first["original_path"].write_bytes(JPEG_ORIGINAL)
        first["thumbnail_path"].write_bytes(JPEG_THUMBNAIL)
        saved = self.store.commit_screenshot_capture(
            self.recording_id,
            request_id="same-request",
            token=first["token"],
            capture=self._capture(),
        )

        second = self.store.reserve_screenshot_capture(
            self.recording_id,
            request_id="same-request",
        )

        self.assertEqual(second["existing"]["screenshot_id"], saved["screenshot_id"])
        self.assertEqual(len(self.store.list_screenshots(self.recording_id)), 1)

    def test_discard_removes_failed_capture_staging(self) -> None:
        staging = self.store.reserve_screenshot_capture(
            self.recording_id,
            request_id="request-failed",
        )
        staging["original_path"].write_bytes(JPEG_ORIGINAL)
        staging["thumbnail_path"].write_bytes(JPEG_THUMBNAIL)

        self.store.discard_screenshot_capture(self.recording_id, staging["token"])

        self.assertFalse(staging["original_path"].exists())
        self.assertFalse(staging["thumbnail_path"].exists())


if __name__ == "__main__":
    unittest.main()
