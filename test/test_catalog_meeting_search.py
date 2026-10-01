from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_asr_server.catalog import CatalogStore
from local_asr_server.catalog_search import CatalogMeetingSearch


class CatalogMeetingSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "closedroom.db"
        self.catalog = CatalogStore(self.db_path)
        self.search = CatalogMeetingSearch(self.catalog)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _recording(self, index: int, *, title: str | None = None, project: str = "") -> dict:
        return {
            "id": f"recording-{index:04d}",
            "title": title or f"Meeting {index:04d}",
            "project_name": project,
            "status": "completed",
            "created_at": f"2026-08-{(index % 28) + 1:02d}T12:{index % 60:02d}:00+00:00",
            "completed_at": f"2026-08-{(index % 28) + 1:02d}T13:{index % 60:02d}:00+00:00",
            "mime_type": "audio/wav",
            "extension": ".wav",
            "chunk_count": 1,
            "bytes_written": 100,
            "relative_dir": f"2026-08-01/recording-{index:04d}",
            "capture_mode": "mic_only",
            "primary_track_id": "mic",
            "audio_tracks": [],
            "capture_backend": "native",
            "capture_status": "stopped",
            "warnings": [],
        }

    def _transcription(self, recording_id: str, text: str, *, item_id: str = "transcript-1") -> dict:
        return {
            "id": f"{recording_id}-{item_id}",
            "timestamp": "2026-08-31T15:00:00+00:00",
            "audio_filename": "recording.wav",
            "recording_id": recording_id,
            "model": "test",
            "language": "it",
            "text": text,
            "segments": [],
            "stats": {},
            "hidden": False,
            "merged_into": None,
        }

    def _analysis_run(self, recording_id: str, *, run_id: str, markdown: str, created_at: float) -> dict:
        return {
            "id": run_id,
            "job_id": f"job-{run_id}",
            "scope_type": "recording",
            "scope_id": recording_id,
            "recording_id": recording_id,
            "transcription_id": None,
            "analysis_type": "meeting_brief",
            "provider": "local",
            "model": "test",
            "reasoning": "off",
            "show_thinking": False,
            "json_mode": True,
            "prompt_version": "test-v1",
            "input_hash": f"hash-{run_id}",
            "status": "completed",
            "result": {"markdown": markdown},
            "result_markdown": markdown,
            "created_at": created_at,
            "completed_at": created_at + 1,
        }

    def test_search_reaches_content_beyond_old_preview_limit(self) -> None:
        for index in range(240):
            self.catalog.upsert_recording(self._recording(index))
        target_id = "recording-0003"
        self.catalog.upsert_transcription(
            self._transcription(target_id, "Discussione riservata su progetto orizzonte zaffiro")
        )

        result = self.search.search(query="zaffiro", page=1, limit=10)

        self.assertEqual(result.recording_ids, [target_id])
        self.assertEqual(result.total, 1)
        self.assertFalse(result.has_more)

    def test_blank_archive_pagination_is_stable_and_bounded(self) -> None:
        for index in range(125):
            self.catalog.upsert_recording(self._recording(index, project="Atlas" if index % 2 else "Orion"))

        first = self.search.search(query="", page=1, limit=25)
        second = self.search.search(query="", page=2, limit=25)
        oversized = self.search.search(query="", page=1, limit=500)

        self.assertEqual(first.total, 125)
        self.assertEqual(len(first.recording_ids), 25)
        self.assertEqual(len(second.recording_ids), 25)
        self.assertTrue(first.has_more)
        self.assertTrue(set(first.recording_ids).isdisjoint(second.recording_ids))
        self.assertEqual(oversized.limit, 50)
        self.assertLessEqual(len(oversized.recording_ids), 50)

    def test_exact_project_filter_and_text_search_compose(self) -> None:
        self.catalog.upsert_recording(self._recording(1, title="Roadmap Nebula", project="Atlas"))
        self.catalog.upsert_recording(self._recording(2, title="Roadmap Nebula", project="Orion"))

        result = self.search.search(query="Nebula", project_name="Atlas", page=1, limit=10)

        self.assertEqual(result.recording_ids, ["recording-0001"])
        self.assertEqual(result.total, 1)

    def test_projection_refreshes_after_recording_transcript_and_delete_mutations(self) -> None:
        recording_id = "recording-0001"
        self.catalog.upsert_recording(self._recording(1, title="Alpha title"))
        self.assertEqual(self.search.search(query="Alpha").recording_ids, [recording_id])

        self.catalog.upsert_recording(self._recording(1, title="Beta title"))
        self.assertEqual(self.search.search(query="Alpha").recording_ids, [])
        self.assertEqual(self.search.search(query="Beta").recording_ids, [recording_id])

        transcript = self._transcription(recording_id, "first transcript keyword apricot")
        self.catalog.upsert_transcription(transcript)
        self.assertEqual(self.search.search(query="apricot").recording_ids, [recording_id])

        transcript["text"] = "replacement transcript keyword kumquat"
        self.catalog.upsert_transcription(transcript)
        self.assertEqual(self.search.search(query="apricot").recording_ids, [])
        self.assertEqual(self.search.search(query="kumquat").recording_ids, [recording_id])

        self.catalog.delete_recording(recording_id)
        self.assertEqual(self.search.search(query="kumquat").recording_ids, [])

    def test_latest_completed_note_revision_is_indexed_and_edit_updates_refresh(self) -> None:
        recording_id = "recording-0004"
        self.catalog.upsert_recording(self._recording(4))
        old = self._analysis_run(
            recording_id,
            run_id="run-old",
            markdown="Old decision keyword marigold",
            created_at=10.0,
        )
        new = self._analysis_run(
            recording_id,
            run_id="run-new",
            markdown="Current decision keyword lavender",
            created_at=20.0,
        )
        self.catalog.create_analysis_run(old)
        self.catalog.create_analysis_run(new)

        self.assertEqual(self.search.search(query="marigold").recording_ids, [])
        self.assertEqual(self.search.search(query="lavender").recording_ids, [recording_id])

        self.catalog.update_analysis_run(
            "run-new",
            status="completed",
            result={"markdown": "Edited current decision keyword verbena"},
        )
        self.assertEqual(self.search.search(query="lavender").recording_ids, [])
        self.assertEqual(self.search.search(query="verbena").recording_ids, [recording_id])

    def test_reopen_preserves_complete_search_projection(self) -> None:
        recording_id = "recording-0009"
        self.catalog.upsert_recording(self._recording(9, title="Persistent Quasar"))
        self.assertEqual(self.search.search(query="Quasar").recording_ids, [recording_id])

        reopened = CatalogMeetingSearch(CatalogStore(self.db_path))

        self.assertEqual(reopened.search(query="Quasar").recording_ids, [recording_id])

    def test_user_query_is_plain_text_not_raw_fts_syntax(self) -> None:
        self.catalog.upsert_recording(self._recording(1, title="Budget Q4 planning"))

        result = self.search.search(query='Budget: (Q4) OR "broken"*', page=1, limit=10)

        self.assertIsInstance(result.recording_ids, list)


if __name__ == "__main__":
    unittest.main()
