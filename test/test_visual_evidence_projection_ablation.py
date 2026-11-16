"""E5: public visual evidence remains identical for available and unavailable screenshots.

No SQLite migration, manifest writes, or real media processing.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.recordings import RecordingStore


class VisualEvidenceProjectionAblationTests(unittest.TestCase):
    def test_available_missing_and_continuous_sources_remain_ordered_and_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordingStore(Path(tmp), use_settings_dir=False)
            recording = store.create(title="Projection", mime_type="audio/wav", model="test", language="it")
            recording_id = recording["id"]
            screenshots = [
                {"screenshot_id": "available-shot", "sequence": 1, "timestamp": 7.0,
                 "available": True, "sha256": "a", "display_id": 2, "display_title": "Display A"},
                {"screenshot_id": "unavailable-shot", "sequence": 2, "timestamp": 2.0,
                 "available": False, "sha256": "b", "display_id": 4, "display_title": "Display B"},
            ]
            frames = [{"sequence": 3, "timestamp": 5.0, "path": Path("/fixture/frame.jpg")}]
            available_path = Path(tmp) / "available.jpg"
            with patch.object(store, "list_visual_frames", return_value=frames), \
                    patch.object(store, "list_screenshots", return_value=screenshots), \
                    patch.object(store, "screenshot_asset_path", return_value=available_path) as get_asset:
                result = store.list_visual_evidence_frames(recording_id)
            get_asset.assert_called_once_with(recording_id, "available-shot", thumbnail=False)
            self.assertEqual([i["timestamp"] for i in result], [2.0, 5.0, 7.0])
            self.assertEqual(result[0], {
                "sequence": 1_000_000_002, "timestamp": 2.0, "path": None,
                "evidence_source": "manual_screenshot", "capture_kind": "manual",
                "evidence_id": "unavailable-shot", "screenshot_id": "unavailable-shot",
                "sha256": "b", "display_id": 4, "display_title": "Display B",
                "available": False,
            })
            self.assertEqual(result[2], {
                "sequence": 1_000_000_001, "timestamp": 7.0, "path": available_path,
                "evidence_source": "manual_screenshot", "capture_kind": "manual",
                "evidence_id": "available-shot", "screenshot_id": "available-shot",
                "sha256": "a", "display_id": 2, "display_title": "Display A",
                "available": True,
            })
            self.assertEqual(result[1]["evidence_source"], "continuous_frame")
            self.assertEqual(result[1]["evidence_id"], "visual-frame-3")
            self.assertEqual(result[1]["capture_kind"], "automatic")

    def test_missing_asset_never_resolves_path_and_retains_false_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordingStore(Path(tmp), use_settings_dir=False)
            recording = store.create(title="Missing", mime_type="audio/wav", model="test", language="it")
            with patch.object(store, "list_visual_frames", return_value=[]), \
                    patch.object(store, "list_screenshots", return_value=[{
                        "sequence": 0, "timestamp": 0, "available": False,
                        "sha256": None, "display_id": None, "display_title": None,
                        "screenshot_id": None,
                    }]), \
                    patch.object(store, "screenshot_asset_path", side_effect=AssertionError("unavailable must not resolve")):
                result = store.list_visual_evidence_frames(recording["id"])
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["path"], None)
            self.assertEqual(result[0]["available"], False)
            self.assertEqual(result[0]["sequence"], 1_000_000_000)


if __name__ == "__main__":
    unittest.main()
