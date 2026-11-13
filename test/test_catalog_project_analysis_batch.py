from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_asr_server.catalog import CatalogStore
from local_asr_server.routers.helpers import _build_projects


class ProjectAnalysisBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog = CatalogStore(Path(self.tmp.name) / "catalog.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, index: int, *, recording: str | None, transcript: str | None) -> dict:
        return {
            "id": f"analysis-{index:04d}",
            "scope_type": "recording" if recording else "transcription",
            "scope_id": recording or transcript,
            "recording_id": recording,
            "transcription_id": transcript,
            "analysis_type": "meeting_brief",
            "provider": "local",
            "input_hash": f"hash-{index}",
            "prompt_version": "test-v1",
            "status": "completed",
            "created_at": float(index),
            "result": {"markdown": f"result {index}"},
        }

    def test_matches_scalar_per_source_latest_and_per_source_limit(self) -> None:
        for i in range(120):
            self.catalog.create_analysis_run(
                self._run(i, recording="meeting-1" if i < 60 else "meeting-2", transcript=None)
            )
        self.catalog.create_analysis_run(self._run(120, recording=None, transcript="transcript-2"))
        self.catalog.create_analysis_run(self._run(121, recording="meeting-1", transcript="transcript-1"))
        for source_key, keys in (
            ("recording_id", ["meeting-1", "meeting-2", "unknown", "meeting-1"]),
            ("transcription_id", ["transcript-1", "transcript-2", "unknown"]),
        ):
            grouped = self.catalog.list_analysis_runs_grouped(source_key, keys, limit=50)
            for key in set(keys):
                scalar = self.catalog.list_analysis_runs(**{source_key: key}, limit=50)
                self.assertEqual(grouped.get(key, []), scalar)
        self.assertEqual(self.catalog.list_analysis_runs_grouped("recording_id", []), {})
        with self.assertRaises(ValueError):
            self.catalog.list_analysis_runs_grouped("scope_id", ["meeting-1"])

    def test_405_sources_take_two_bounded_reads_not_405(self) -> None:
        self.catalog.create_analysis_run(self._run(1, recording="meeting-000", transcript=None))
        ids = [f"meeting-{i:03d}" for i in range(405)]
        with patch.object(self.catalog, "connection", wraps=self.catalog.connection) as connection:
            grouped = self.catalog.list_analysis_runs_grouped("recording_id", ids)
        self.assertEqual(connection.call_count, 2)
        self.assertEqual(list(grouped), ["meeting-000"])

    def test_projects_reuses_grouped_reads_and_keeps_single_canonical_run(self) -> None:
        recording = {"id": "meeting-1", "project_name": "Atlas", "status": "completed"}
        transcription = {"id": "transcript-1", "analysis": None, "segments": [], "stats": {}}
        run = self._run(1, recording="meeting-1", transcript="transcript-1")
        catalog = SimpleNamespace(
            list_analysis_runs_grouped=Mock(side_effect=[
                {"meeting-1": [run]},
                {"transcript-1": [run]},
            ]),
            list_analysis_runs=Mock(side_effect=AssertionError("N+1 fallback")),
        )
        services = SimpleNamespace(
            recordings=SimpleNamespace(list=Mock(return_value=[recording])),
            transcriptions=SimpleNamespace(find_for_recordings=Mock(return_value={"meeting-1": transcription})),
            catalog=catalog,
            transcription_jobs=SimpleNamespace(list=Mock(return_value=[])),
        )
        with patch("local_asr_server.routers.helpers.get_services", return_value=services):
            result = _build_projects(SimpleNamespace())
        item = result["items"][0]["items"][0]
        self.assertEqual(len(item["analysis_runs"]), 1)
        self.assertEqual(item["analysis_runs"][0]["id"], run["id"])
        self.assertEqual(catalog.list_analysis_runs_grouped.call_count, 2)
        catalog.list_analysis_runs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
