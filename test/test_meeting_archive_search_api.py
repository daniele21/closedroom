from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from local_asr_server.server import create_app
from support import deterministic_settings


class MeetingArchiveSearchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings_patcher = patch("local_asr_server.transcriptions.load_settings")
        self.mock_load_settings = self.settings_patcher.start()
        self.mock_load_settings.return_value = deterministic_settings(
            root,
            recordings_dir=self.temp_dir.name,
        )
        self.app = create_app(
            default_model="test-model",
            recordings_dir=root,
            enable_auth=False,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.settings_patcher.stop()
        self.temp_dir.cleanup()

    def _create(self, title: str, project: str = "") -> str:
        response = self.client.post(
            "/v1/recordings",
            json={
                "title": title,
                "project_name": project,
                "mime_type": "audio/webm",
                "capture_mode": "mic_only",
            },
        )
        self.assertEqual(response.status_code, 201)
        return str(response.json()["id"])

    def test_search_finds_meeting_outside_recent_preview_and_returns_page_contract(self) -> None:
        target_id = self._create("Archive needle zephyr", "Atlas")
        for index in range(105):
            self._create(f"Recent meeting {index:03d}", "Orion")

        response = self.client.get(
            "/v1/meetings",
            params={"q": "zephyr", "page": 1, "limit": 10},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([item["id"] for item in data["items"]], [target_id])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["limit"], 10)
        self.assertFalse(data["has_more"])

    def test_blank_query_pages_complete_archive_and_composes_project_filter(self) -> None:
        for index in range(63):
            self._create(
                f"Paged meeting {index:03d}",
                "Atlas" if index % 2 else "Orion",
            )

        first = self.client.get(
            "/v1/meetings",
            params={"q": "", "page": 1, "limit": 20, "project_name": "Atlas"},
        )
        second = self.client.get(
            "/v1/meetings",
            params={"q": "", "page": 2, "limit": 20, "project_name": "Atlas"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_data = first.json()
        second_data = second.json()
        self.assertEqual(first_data["total"], 31)
        self.assertEqual(len(first_data["items"]), 20)
        self.assertEqual(len(second_data["items"]), 11)
        self.assertTrue(first_data["has_more"])
        self.assertFalse(second_data["has_more"])
        self.assertTrue(
            set(item["id"] for item in first_data["items"]).isdisjoint(
                item["id"] for item in second_data["items"]
            )
        )

    def test_existing_recent_meetings_call_remains_backward_compatible(self) -> None:
        self._create("Compatibility meeting")

        response = self.client.get("/v1/meetings", params={"limit": 50})

        self.assertEqual(response.status_code, 200)
        self.assertIn("items", response.json())
        self.assertNotIn("page", response.json())


if __name__ == "__main__":
    unittest.main()
