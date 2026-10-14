from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_asr_server.catalog import CatalogStore
from local_asr_server.jobs import JobStore
from local_asr_server.transcription_jobs import TranscriptionJobManager


class JobStoreTests(unittest.TestCase):
    def test_create_update_and_reopen_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closedroom.db"
            store = JobStore(db_path)

            created = store.create(
                job_id="job-1",
                job_type="transcription",
                scope_type="recording",
                scope_id="rec-1",
                payload={"recording_id": "rec-1"},
            )
            self.assertEqual(created["status"], "queued")
            self.assertEqual(created["scope_id"], "rec-1")

            updated = store.update(
                "job-1",
                status="completed",
                current_step="done",
                progress=100,
                progress_detail={"kind": "visual_processing_progress", "processed": 3},
                result={"text": "Ciao"},
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated["status"], "completed")
            self.assertEqual(updated["result"], {"text": "Ciao"})
            self.assertEqual(updated["progress_detail"]["processed"], 3)
            self.assertIsNotNone(updated["completed_at"])

            reopened = JobStore(db_path)
            persisted = reopened.get("job-1")
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["result"], {"text": "Ciao"})
            self.assertEqual(persisted["progress_detail"]["processed"], 3)

            events = reopened.events_after("job-1")
            self.assertIsNotNone(events)
            self.assertEqual([event["sequence"] for event in events], [1, 2])
            self.assertEqual(events[-1]["status"], "completed")

    def test_job_event_history_is_bounded_without_renumbering_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db", event_capacity=3)
            store.create(job_id="job-1", job_type="transcription")
            for progress in (10, 20, 30, 40):
                store.update(
                    "job-1",
                    status="running",
                    current_step="transcribing",
                    progress=progress,
                )

            events = store.events_after("job-1")

            self.assertIsNotNone(events)
            self.assertEqual([event["sequence"] for event in events], [3, 4, 5])
            self.assertEqual([event["progress"] for event in events], [20, 30, 40])
            self.assertEqual(store.events_after("job-1", 4)[0]["sequence"], 5)

    def test_job_event_capacity_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "event_capacity"):
                JobStore(Path(tmp) / "closedroom.db", event_capacity=0)

    def test_persisted_job_manager_does_not_duplicate_events_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db")
            manager = TranscriptionJobManager(store)
            created = manager.create("rec-1", lambda _job: {"text": "Ciao"})
            job_id = created["id"]

            import time

            for _ in range(20):
                if store.get(job_id)["status"] == "completed":
                    break
                time.sleep(0.05)

            self.assertEqual(manager._jobs[job_id].events.qsize(), 0)
            self.assertGreaterEqual(len(store.events_after(job_id)), 2)

    def test_list_jobs_filters_by_type_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db")
            store.create(
                job_id="job-1",
                job_type="transcription",
                scope_type="recording",
                scope_id="rec-1",
            )
            store.create(
                job_id="job-2",
                job_type="analysis",
                scope_type="recording",
                scope_id="rec-1",
            )

            transcription_jobs = store.list_jobs(job_type="transcription")
            self.assertEqual([job["id"] for job in transcription_jobs], ["job-1"])

            recording_jobs = store.list_jobs(scope_type="recording", scope_id="rec-1")
            self.assertEqual({job["id"] for job in recording_jobs}, {"job-1", "job-2"})

    def test_submission_identity_is_atomic_and_survives_terminal_restart(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db")

            def submit(index: int):
                return store.create_or_get_submission(
                    job_id=f"job-{index}",
                    job_type="transcription",
                    scope_type="recording",
                    scope_id="recording-1",
                    request_id="same-click",
                    request_hash="unchanged-options",
                    payload={"recording_id": "recording-1"},
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                admitted = list(pool.map(submit, range(16)))
            self.assertEqual(sum(int(created) for _, created in admitted), 1)
            self.assertEqual(len({job["id"] for job, _ in admitted}), 1)
            job_id = admitted[0][0]["id"]
            store.update(job_id, status="completed", result={"text": "private"})
            reopened = JobStore(store.db_path)
            same, created = reopened.create_or_get_submission(
                job_id="should-not-create",
                job_type="transcription",
                scope_type="recording",
                scope_id="recording-1",
                request_id="same-click",
                request_hash="unchanged-options",
            )
            self.assertFalse(created)
            self.assertEqual(same["id"], job_id)
            self.assertEqual(same["status"], "completed")
            with self.assertRaisesRegex(ValueError, "different options"):
                reopened.create_or_get_submission(
                    job_id="invalid-collision",
                    job_type="transcription",
                    scope_type="recording",
                    scope_id="recording-1",
                    request_id="same-click",
                    request_hash="changed-options",
                )
            retry, created = reopened.create_or_get_submission(
                job_id="explicit-retry",
                job_type="transcription",
                scope_type="recording",
                scope_id="recording-1",
                request_id="new-click",
                request_hash="unchanged-options",
            )
            self.assertTrue(created)
            self.assertEqual(retry["id"], "explicit-retry")

    def test_restart_interrupts_old_active_jobs_beyond_recent_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db")
            with store.connection() as conn:
                for index in range(510):
                    conn.execute(
                        "INSERT INTO jobs (id, type, status, current_step, "
                        "progress, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                        (
                            f"job-{index}", "analysis",
                            "queued" if index == 0 else "completed",
                            "queued" if index == 0 else "completed",
                            float(index), float(index),
                        ),
                    )
            interrupted = store.interrupt_incomplete()
            self.assertEqual([item["id"] for item in interrupted], ["job-0"])
            self.assertEqual(store.get("job-0")["status"], "interrupted")
            self.assertEqual(store.interrupt_incomplete(), [])

    def test_has_active_job_avoids_materializing_job_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db")
            store.create(job_id="job-1", job_type="transcription")
            store.create(job_id="job-2", job_type="analysis")

            self.assertTrue(store.has_active_job())
            self.assertTrue(store.has_active_job(job_type="transcription"))
            self.assertTrue(store.has_active_job(job_type="analysis"))

            store.update("job-1", status="completed", result={"large": "payload"})
            self.assertFalse(store.has_active_job(job_type="transcription"))
            self.assertTrue(store.has_active_job(job_type="analysis"))

            store.update("job-2", status="failed", error="boom")
            self.assertFalse(store.has_active_job())

    def test_missing_job_events_return_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db")
            self.assertIsNone(store.events_after("missing"))

    def test_restart_marks_incomplete_job_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "closedroom.db")
            store.create(job_id="job-1", job_type="transcription")
            interrupted = store.interrupt_incomplete()
            self.assertEqual([job["id"] for job in interrupted], ["job-1"])
            self.assertEqual(store.get("job-1")["status"], "interrupted")
            self.assertEqual(store.get("job-1")["error"], "Interrupted by server restart")

    def test_analysis_runs_are_persisted_and_filterable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog = CatalogStore(Path(tmp) / "closedroom.db")
            catalog.create_analysis_run(
                {
                    "id": "run-1",
                    "job_id": "job-1",
                    "scope_type": "transcription",
                    "scope_id": "trans-1",
                    "transcription_id": "trans-1",
                    "provider": "mock",
                    "model": "nemotron-nano-4b",
                    "temperature": 0.2,
                    "reasoning": "auto",
                    "effective_reasoning": None,
                    "show_thinking": False,
                    "max_output_tokens": None,
                    "json_mode": True,
                    "llm_options": {"quality_preset": "balanced"},
                    "prompt_version": "summary_v1",
                    "input_hash": "abc123",
                    "status": "queued",
                    "created_at": 123.0,
                }
            )

            catalog.update_analysis_run(
                "run-1",
                status="completed",
                result={"summary": "Sintesi"},
                completed_at=124.0,
            )

            run = catalog.get_analysis_run("run-1")
            self.assertIsNotNone(run)
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["result"], {"summary": "Sintesi"})
            self.assertEqual(run["llm_options"], {"quality_preset": "balanced"})

            runs = catalog.list_analysis_runs(scope_type="transcription", scope_id="trans-1")
            self.assertEqual([item["id"] for item in runs], ["run-1"])

    def test_transcription_job_manager_recovers_persisted_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closedroom.db"
            store = JobStore(db_path)
            manager = TranscriptionJobManager(store)

            created = manager.create("rec-1", lambda _job: {"text": "Ciao"})
            job_id = created["id"]

            import time

            recovered = None
            for _ in range(20):
                recovered = TranscriptionJobManager(JobStore(db_path)).get(job_id)
                if recovered and recovered["status"] == "completed":
                    break
                time.sleep(0.05)

            self.assertIsNotNone(recovered)
            self.assertEqual(recovered["status"], "completed")
            self.assertEqual(recovered["result"], {"text": "Ciao"})


    def test_activities_discover_old_active_phases_without_loading_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / 'jobs.db')
            store.create(job_id='old-active', job_type='transcription', scope_type='recording', scope_id='rec')
            store.update('old-active', status='transcribing_system', current_step='transcribing_system',
                         progress=50, progress_detail={'kind': 'asr_track_progress', 'track_percent': 40},
                         result={'text': 'PRIVATE RESULT'})
            with store.connection() as conn:
                for index in range(510):
                    store._insert_job(conn, job_id=f'done-{index}', job_type='analysis', scope_type='inline_text',
                                      scope_id='run', payload={'text': 'PRIVATE PROMPT'}, status='completed',
                                      current_step='completed', progress=100, dedupe_key=None, now=9999999999 + index)
            self.assertTrue(store.has_active_job(job_type='transcription'))
            items = store.activity_summaries(recent_limit=3)
            self.assertEqual(len(items), 4)
            self.assertEqual(items[0]['id'], 'old-active')
            self.assertEqual(items[0]['progress_detail']['track_percent'], 40)
            self.assertTrue(all('payload' not in item and 'result' not in item for item in items))

if __name__ == "__main__":
    unittest.main()
