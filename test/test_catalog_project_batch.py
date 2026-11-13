from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_asr_server.catalog import CatalogStore
from local_asr_server.routers.helpers import _build_projects


def transcript(recording: str, suffix: str, timestamp: str, *, merged_into: str | None = None) -> dict:
    return {
        "id": f"{recording}-{suffix}",
        "recording_id": recording,
        "timestamp": timestamp,
        "audio_filename": f"{recording}.wav",
        "model": "test",
        "language": "it",
        "text": f"Test {suffix}",
        "segments": [],
        "stats": {},
        "hidden": bool(merged_into),
        "merged_into": merged_into,
    }


class CatalogProjectBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.catalog = CatalogStore(Path(self.temp_dir.name) / "closedroom.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_batch_matches_latest_and_merged_transcription_semantics(self) -> None:
        earlier = transcript("meeting-a", "early", "2026-09-01T09:00:00+00:00")
        latest = transcript("meeting-a", "latest", "2026-09-03T09:00:00+00:00")
        canonical = transcript("meeting-b", "canonical", "2026-09-02T09:00:00+00:00")
        alias = transcript(
            "meeting-c", "alias", "2026-09-04T09:00:00+00:00",
            merged_into=canonical["id"],
        )
        for item in (earlier, latest, canonical, alias):
            self.catalog.upsert_transcription(item)
        ids = ["meeting-a", "meeting-b", "meeting-c", "meeting-missing", "meeting-a"]
        result = self.catalog.find_transcriptions_for_recordings(ids)
        self.assertEqual(set(result), {"meeting-a", "meeting-b", "meeting-c"})
        for recording_id in result:
            original = self.catalog.find_transcription_for_recording(recording_id)
            self.assertEqual(result[recording_id], original)
        self.assertEqual(result["meeting-a"]["id"], latest["id"])
        self.assertEqual(result["meeting-c"]["id"], canonical["id"])
        self.assertEqual(self.catalog.find_transcriptions_for_recordings([]), {})

    def test_405_recording_ids_use_only_two_bounded_selects(self) -> None:
        self.catalog.upsert_transcription(transcript("meeting-000", "only", "2026-09-01T09:00:00+00:00"))
        ids = [f"meeting-{i:03d}" for i in range(405)]
        with patch.object(self.catalog, "connection", wraps=self.catalog.connection) as connection:
            items = self.catalog.find_transcriptions_for_recordings(ids)
        self.assertEqual(connection.call_count, 2)
        self.assertEqual(list(items), ["meeting-000"])

    def test_projects_owner_reuses_batch_and_keeps_response_shape(self) -> None:
        recordings = [
            {"id": f"meeting-{i:03d}", "project_name": "ClosedRoom", "status": "completed"}
            for i in range(5)
        ]
        services = SimpleNamespace(
            recordings=SimpleNamespace(list=Mock(return_value=recordings)),
            transcriptions=SimpleNamespace(
                find_for_recordings=Mock(return_value={}),
                find_for_recording=Mock(side_effect=AssertionError("N+1 fallback")),
            ),
            catalog=SimpleNamespace(list_analysis_runs=Mock(return_value=[])),
            transcription_jobs=SimpleNamespace(list=Mock(return_value=[])),
        )
        with patch("local_asr_server.routers.helpers.get_services", return_value=services):
            result = _build_projects(SimpleNamespace())
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["items"][0]["items"]), 5)
        services.transcriptions.find_for_recordings.assert_called_once_with(
            [item["id"] for item in recordings]
        )
        services.transcriptions.find_for_recording.assert_not_called()


if __name__ == "__main__":
    unittest.main()
