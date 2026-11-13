from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_asr_server.jobs import JobStore
from local_asr_server.routers.helpers import _build_projects
from local_asr_server.transcription_jobs import TranscriptionJob, TranscriptionJobManager


class ProjectPreparationJobBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.manager = TranscriptionJobManager(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _insert(self, job_id: str, recording_id: str, *, job_type: str = "meeting_preparation") -> None:
        self.store.create(
            job_id=job_id, job_type=job_type,
            scope_type="recording", scope_id=recording_id,
            payload={"recording_id": recording_id},
        )

    def test_grouped_matches_existing_per_recording_jobs_and_limit(self) -> None:
        for index in range(56):
            self._insert(f"prep-1-{index:03d}", "meeting-1")
        for index in range(3):
            self._insert(f"prep-2-{index}", "meeting-2")
        self._insert("wrong-type", "meeting-1", job_type="transcription")
        ids = ["meeting-1", "meeting-2", "missing", "meeting-1"]
        grouped = self.manager.list_grouped(
            job_type="meeting_preparation", scope_type="recording", scope_ids=ids, limit=50,
        )
        for recording_id in set(ids):
            expected = self.manager.list(
                job_type="meeting_preparation", scope_type="recording",
                scope_id=recording_id, limit=50,
            )
            self.assertEqual(grouped.get(recording_id, []), expected)
        self.assertEqual(len(grouped["meeting-1"]), 50)
        self.assertEqual(self.manager.list_grouped(
            job_type="meeting_preparation", scope_type="recording", scope_ids=[],
        ), {})

    def test_1_25_200_source_reads_are_bounded_and_405_chunk_to_two(self) -> None:
        self._insert("only-job", "meeting-000")
        for size, expected_reads in ((1, 1), (25, 1), (200, 1), (405, 2)):
            with self.subTest(size=size), patch.object(
                self.store, "connection", wraps=self.store.connection,
            ) as connection:
                ids = [f"meeting-{i:03d}" for i in range(size)]
                result = self.manager.list_grouped(
                    job_type="meeting_preparation", scope_type="recording", scope_ids=ids,
                )
            self.assertEqual(connection.call_count, expected_reads)
            self.assertEqual(result["meeting-000"][0]["id"], "only-job")

    def test_transient_in_memory_manager_has_same_semantics(self) -> None:
        manager = TranscriptionJobManager()
        for i in range(3):
            job = TranscriptionJob(
                id=f"temporary-{i}", recording_id="meeting-a",
                job_type="meeting_preparation", scope_id="meeting-a",
                created_at=float(i + 1),
            )
            manager._jobs[job.id] = job
        grouped = manager.list_grouped(
            job_type="meeting_preparation", scope_type="recording",
            scope_ids=["meeting-a", "meeting-b"], limit=2,
        )
        expected = manager.list(
            job_type="meeting_preparation", scope_type="recording", scope_id="meeting-a", limit=2,
        )
        self.assertEqual(grouped["meeting-a"], expected)
        self.assertNotIn("meeting-b", grouped)

    def test_project_read_model_reuses_batch_and_retains_failed_pipeline_suppression(self) -> None:
        recordings = [
            {"id": "meeting-1", "project_name": "Atlas", "status": "completed"},
            {"id": "meeting-2", "project_name": "Atlas", "status": "completed"},
        ]
        failed = {
            "id": "job-failed", "type": "meeting_preparation",
            "status": "failed", "result": {"pipeline_run_id": "pipeline-failed"},
        }
        valid_run = {
            "id": "analysis-1", "pipeline_run_id": "pipeline-failed",
            "status": "completed", "analysis_type": "meeting_brief",
            "created_at": 1,
        }
        jobs = SimpleNamespace(
            list_grouped=Mock(return_value={"meeting-1": [failed]}),
            list=Mock(side_effect=AssertionError("N+1 job list")),
        )
        services = SimpleNamespace(
            recordings=SimpleNamespace(list=Mock(return_value=recordings)),
            transcriptions=SimpleNamespace(find_for_recordings=Mock(return_value={})),
            catalog=SimpleNamespace(list_analysis_runs=Mock(return_value=[]),
                                    list_analysis_runs_grouped=Mock(side_effect=[
                                        {"meeting-1": [valid_run]}, {},
                                    ])),
            transcription_jobs=jobs,
        )
        with patch("local_asr_server.routers.helpers.get_services", return_value=services):
            result = _build_projects(SimpleNamespace())
        items = result["items"][0]["items"]
        self.assertEqual(len(items), 2)
        self.assertIsNone(items[0]["analysis"])
        self.assertEqual(items[0]["analysis_runs"][0]["id"], "analysis-1")
        jobs.list_grouped.assert_called_once_with(
            job_type="meeting_preparation", scope_type="recording",
            scope_ids=["meeting-1", "meeting-2"], limit=50,
        )
        jobs.list.assert_not_called()


if __name__ == "__main__":
    unittest.main()
