from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from local_asr_server.jobs import JobStore
from local_asr_server.meeting_preparation import (
    MEETING_PREPARATION_JOB_TYPE,
    MeetingPreparationManager,
)


class FakeRecordings:
    def __init__(self, root: Path) -> None:
        self.audio = root / "mic.wav"
        self.audio.write_bytes(b"audio-source")
        self.recording = {
            "id": "rec-1",
            "status": "recorded",
            "audio_tracks": [
                {
                    "id": "mic",
                    "source": "mic",
                    "bytes_written": len(b"audio-source"),
                    "chunk_count": 1,
                    "chunks": [
                        {"sequence": 0, "sha256": "source-hash", "size": len(b"audio-source")},
                    ],
                }
            ],
        }

    def get(self, recording_id: str, include_result: bool = False):
        if recording_id != "rec-1":
            raise KeyError(recording_id)
        return self.recording

    def transcribable_tracks(self, recording_id: str):
        self.get(recording_id)
        return [(self.recording["audio_tracks"][0], self.audio)]


class FakeTranscriptionService:
    @staticmethod
    def resolve_asr(settings, **kwargs):
        return "local", "test-model", {}, {}


class FakeTranscriptions:
    def __init__(self) -> None:
        self.current = None

    def find_for_recording(self, recording_id: str):
        return self.current


class FakeAnalysisJobs:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.cancelled = []

    @staticmethod
    def pipeline_identity(_body):
        return {
            "pipeline_id": "meeting_default",
            "templates": [
                {"id": "meeting_brief", "version": "v1"},
                {"id": "action_items", "version": "v1"},
                {"id": "decisions", "version": "v1"},
                {"id": "risks_blockers", "version": "v1"},
            ],
            "llm": {"provider": "mock", "model": ""},
        }

    def cancel(self, job_id: str):
        self.cancelled.append(job_id)
        return self.store.update(job_id, status="cancelled", current_step="cancelled")


class FakeTranscriptionJobs:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.cancelled = []
        self.callbacks = {}

    def register(self, job_id: str, callback) -> None:
        self.callbacks[job_id] = callback

    def cancel(self, job_id: str):
        self.cancelled.append(job_id)
        snapshot = self.store.update(job_id, status="cancelled", current_step="cancelled")
        callback = self.callbacks.get(job_id)
        if callback and snapshot:
            callback(snapshot)
        return snapshot


class MeetingPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = JobStore(root / "closedroom.db")
        self.recordings = FakeRecordings(root)
        self.transcriptions = FakeTranscriptions()
        self.analysis_jobs = FakeAnalysisJobs(self.store)
        self.transcription_jobs = FakeTranscriptionJobs(self.store)
        self.services = SimpleNamespace(
            jobs=self.store,
            recordings=self.recordings,
            transcription=FakeTranscriptionService(),
            transcriptions=self.transcriptions,
            analysis_jobs=self.analysis_jobs,
            transcription_jobs=self.transcription_jobs,
        )
        self.settings = {"speaker_diarization_enabled": False}
        self.settings_patcher = patch(
            "local_asr_server.meeting_preparation.load_settings",
            return_value=self.settings,
        )
        self.settings_patcher.start()
        self.manager = MeetingPreparationManager(self.services, default_model="test-model")

    def tearDown(self) -> None:
        self.settings_patcher.stop()
        self.temp.cleanup()

    @staticmethod
    def _transcription(transcription_id: str = "trans-1") -> dict:
        return {
            "id": transcription_id,
            "recording_id": "rec-1",
            "asr_provider": "local",
            "model": "test-model",
            "language": "it",
            "provider_options": {},
            "stats": {"speaker_diarization": {"status": "disabled"}},
            "text": "Transcript corrected by the user",
        }

    def _queued_transcription_factory(self, calls: list[str]):
        def factory(callback):
            calls.append("transcription")
            job_id = f"trans-job-{len(calls)}"
            snapshot = self.store.create(
                job_id=job_id,
                job_type="transcription",
                scope_type="recording",
                scope_id="rec-1",
                payload={"recording_id": "rec-1"},
            )
            self.transcription_jobs.register(job_id, callback)
            return snapshot
        return factory

    def _completed_transcription_factory(self, calls: list[str]):
        def factory(callback):
            calls.append("transcription")
            job_id = f"trans-job-{len(calls)}"
            self.store.create(
                job_id=job_id,
                job_type="transcription",
                scope_type="recording",
                scope_id="rec-1",
            )
            self.transcriptions.current = self._transcription()
            snapshot = self.store.update(
                job_id,
                status="completed",
                current_step="completed",
                progress=100,
                result={"saved_id": "trans-1"},
            )
            callback(snapshot)
            return snapshot
        return factory

    def _completed_pipeline_factory(self, calls: list[str]):
        def factory(transcription_id, callback):
            calls.append(f"analysis:{transcription_id}")
            jobs = []
            for index in range(4):
                job_id = f"analysis-{len(calls)}-{index}"
                self.store.create(
                    job_id=job_id,
                    job_type="analysis",
                    scope_type="transcription",
                    scope_id=transcription_id,
                )
                snapshot = self.store.update(
                    job_id,
                    status="completed",
                    current_step="completed",
                    progress=100,
                    result={"analysis_run_id": f"run-{index}"},
                )
                callback(snapshot)
                jobs.append({"job_id": job_id, "analysis_run_id": f"run-{index}", "status": "completed"})
            return {
                "pipeline_run_id": f"pipeline-{len(calls)}",
                "pipeline_id": "meeting_default",
                "status": "queued",
                "jobs": jobs,
            }
        return factory

    def test_duplicate_prepare_returns_same_active_parent(self) -> None:
        transcription_calls = []
        analysis_calls = []
        first = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory(transcription_calls),
            start_pipeline=self._completed_pipeline_factory(analysis_calls),
        )
        second = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory(transcription_calls),
            start_pipeline=self._completed_pipeline_factory(analysis_calls),
        )

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(transcription_calls, ["transcription"])
        self.assertEqual(analysis_calls, [])
        children = self.store.list_children(first["id"], stage="transcription")
        self.assertEqual([child["id"] for child in children], ["trans-job-1"])

    def test_complete_preparation_reuses_terminal_identity(self) -> None:
        transcription_calls = []
        analysis_calls = []
        first = self.manager.create(
            "rec-1",
            start_transcription=self._completed_transcription_factory(transcription_calls),
            start_pipeline=self._completed_pipeline_factory(analysis_calls),
        )
        self.assertEqual(self.store.get(first["id"])["status"], "completed")
        self.assertEqual(self.store.get(first["id"])["result"]["transcription_id"], "trans-1")

        second = self.manager.create(
            "rec-1",
            start_transcription=self._completed_transcription_factory(transcription_calls),
            start_pipeline=self._completed_pipeline_factory(analysis_calls),
        )

        self.assertEqual(second["id"], first["id"])
        self.assertTrue(second["reused_completed"])
        self.assertEqual(transcription_calls, ["transcription"])
        self.assertEqual(analysis_calls, ["analysis:trans-1"])
        self.assertEqual(len(self.store.list_children(first["id"], stage="analysis")), 4)

    def test_cancel_waits_for_child_terminal_observation(self) -> None:
        transcription_calls = []
        parent = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory(transcription_calls),
            start_pipeline=self._completed_pipeline_factory([]),
        )
        child_id = self.store.list_children(parent["id"], stage="transcription")[0]["id"]

        cancelled = self.manager.cancel(parent["id"])

        self.assertEqual(self.transcription_jobs.cancelled, [child_id])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cancelled["cancel_requested"])
        self.assertEqual(self.store.list_children(parent["id"], stage="analysis"), [])

    def test_cancel_during_transcription_admission_cancels_late_linked_child(self) -> None:
        def racing_transcription(callback):
            child = self.store.create(
                job_id="trans-race",
                job_type="transcription",
                scope_type="recording",
                scope_id="rec-1",
            )
            self.transcription_jobs.register(child["id"], callback)
            parent = self.store.list_jobs(
                job_type=MEETING_PREPARATION_JOB_TYPE,
                scope_type="recording",
                scope_id="rec-1",
                limit=1,
            )[0]
            self.manager.cancel(parent["id"])
            return child

        parent = self.manager.create(
            "rec-1",
            start_transcription=racing_transcription,
            start_pipeline=self._completed_pipeline_factory([]),
        )

        self.assertEqual(self.store.get(parent["id"])["status"], "cancelled")
        self.assertEqual(self.store.get("trans-race")["status"], "cancelled")
        self.assertEqual(self.transcription_jobs.cancelled, ["trans-race"])
        self.assertEqual(self.store.list_children(parent["id"], stage="analysis"), [])

    def test_cancel_during_analysis_admission_cancels_late_linked_children(self) -> None:
        self.transcriptions.current = self._transcription()

        def racing_pipeline(transcription_id, _callback):
            jobs = []
            for index in range(2):
                job_id = f"analysis-race-{index}"
                self.store.create(
                    job_id=job_id,
                    job_type="analysis",
                    scope_type="transcription",
                    scope_id=transcription_id,
                )
                jobs.append({"job_id": job_id, "status": "queued"})
            parent = self.store.list_jobs(
                job_type=MEETING_PREPARATION_JOB_TYPE,
                scope_type="recording",
                scope_id="rec-1",
                limit=1,
            )[0]
            self.manager.cancel(parent["id"])
            return {
                "pipeline_run_id": "pipeline-race",
                "pipeline_id": "meeting_default",
                "status": "queued",
                "jobs": jobs,
            }

        parent = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory([]),
            start_pipeline=racing_pipeline,
        )

        self.assertEqual(self.store.get(parent["id"])["status"], "cancelled")
        self.assertEqual(self.analysis_jobs.cancelled, ["analysis-race-0", "analysis-race-1"])
        self.assertEqual(self.store.get("analysis-race-0")["status"], "cancelled")
        self.assertEqual(self.store.get("analysis-race-1")["status"], "cancelled")

    def test_notes_failure_retry_reuses_successful_transcript(self) -> None:
        self.transcriptions.current = self._transcription()
        transcription_calls = []
        pipeline_calls = []

        def failing_pipeline(transcription_id, callback):
            pipeline_calls.append(transcription_id)
            job_id = f"analysis-failed-{len(pipeline_calls)}"
            self.store.create(
                job_id=job_id,
                job_type="analysis",
                scope_type="transcription",
                scope_id=transcription_id,
            )
            snapshot = self.store.update(
                job_id,
                status="failed",
                current_step="failed",
                error="model failed",
            )
            callback(snapshot)
            return {
                "pipeline_run_id": f"pipeline-{len(pipeline_calls)}",
                "pipeline_id": "meeting_default",
                "status": "queued",
                "jobs": [{"job_id": job_id, "status": "failed"}],
            }

        first = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory(transcription_calls),
            start_pipeline=failing_pipeline,
        )
        self.assertEqual(self.store.get(first["id"])["status"], "failed")
        self.assertEqual(transcription_calls, [])

        second = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory(transcription_calls),
            start_pipeline=self._completed_pipeline_factory(pipeline_calls),
        )
        second_state = self.store.get(second["id"])

        self.assertEqual(second_state["status"], "completed")
        self.assertEqual(second_state["result"]["transcription_id"], "trans-1")
        self.assertEqual(second_state["result"]["resumed_from_job_id"], first["id"])
        self.assertEqual(transcription_calls, [])
        self.assertEqual(self.transcriptions.current["text"], "Transcript corrected by the user")

    def test_restart_interrupts_parent_and_explicit_retry_resumes_notes_stage(self) -> None:
        self.transcriptions.current = self._transcription()
        transcription_calls = []
        pipeline_callbacks = {}
        pipeline_calls = []

        def queued_pipeline(transcription_id, callback):
            pipeline_calls.append(transcription_id)
            job_id = f"analysis-queued-{len(pipeline_calls)}"
            pipeline_callbacks[job_id] = callback
            self.store.create(
                job_id=job_id,
                job_type="analysis",
                scope_type="transcription",
                scope_id=transcription_id,
            )
            return {
                "pipeline_run_id": f"pipeline-{len(pipeline_calls)}",
                "pipeline_id": "meeting_default",
                "status": "queued",
                "jobs": [{"job_id": job_id, "status": "queued"}],
            }

        first = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory(transcription_calls),
            start_pipeline=queued_pipeline,
        )
        self.assertEqual(self.store.get(first["id"])["current_step"], "preparing_notes")
        interrupted = self.store.interrupt_incomplete()
        self.assertIn(first["id"], {job["id"] for job in interrupted})

        second = self.manager.create(
            "rec-1",
            start_transcription=self._queued_transcription_factory(transcription_calls),
            start_pipeline=self._completed_pipeline_factory(pipeline_calls),
        )
        second_state = self.store.get(second["id"])

        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(second_state["status"], "completed")
        self.assertEqual(second_state["result"]["resumed_from_job_id"], first["id"])
        self.assertEqual(transcription_calls, [])


class JobStorePreparationContractTests(unittest.TestCase):
    def test_existing_database_adds_dedupe_column_before_creating_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closedroom.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        scope_type TEXT,
                        scope_id TEXT,
                        status TEXT NOT NULL,
                        current_step TEXT,
                        progress INTEGER NOT NULL DEFAULT 0,
                        payload_json TEXT,
                        result_json TEXT,
                        error TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        started_at REAL,
                        completed_at REAL,
                        cancel_requested INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
            store = JobStore(db_path)
            with store.connection() as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
                indexes = {row["name"] for row in conn.execute("PRAGMA index_list(jobs)")}
            self.assertIn("dedupe_key", columns)
            self.assertIn("progress_detail_json", columns)
            self.assertIn("idx_jobs_dedupe", indexes)

    def test_active_dedupe_and_job_links_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closedroom.db"
            store = JobStore(db_path)
            first, created = store.create_or_get_active(
                job_id="parent-1",
                job_type=MEETING_PREPARATION_JOB_TYPE,
                scope_type="recording",
                scope_id="rec-1",
                dedupe_key="same-input",
            )
            duplicate, duplicate_created = store.create_or_get_active(
                job_id="parent-2",
                job_type=MEETING_PREPARATION_JOB_TYPE,
                scope_type="recording",
                scope_id="rec-1",
                dedupe_key="same-input",
            )
            self.assertTrue(created)
            self.assertFalse(duplicate_created)
            self.assertEqual(duplicate["id"], first["id"])

            store.create(
                job_id="child-1",
                job_type="transcription",
                scope_type="recording",
                scope_id="rec-1",
            )
            store.link_child("parent-1", "child-1", stage="transcription")

            reopened = JobStore(db_path)
            children = reopened.list_children("parent-1")
            self.assertEqual(children[0]["id"], "child-1")
            self.assertEqual(children[0]["link_stage"], "transcription")

            reopened.update("parent-1", status="completed", current_step="completed", progress=100)
            replacement, replacement_created = reopened.create_or_get_active(
                job_id="parent-3",
                job_type=MEETING_PREPARATION_JOB_TYPE,
                scope_type="recording",
                scope_id="rec-1",
                dedupe_key="same-input",
            )
            self.assertTrue(replacement_created)
            self.assertEqual(replacement["id"], "parent-3")


if __name__ == "__main__":
    unittest.main()
