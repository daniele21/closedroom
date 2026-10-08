from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from local_asr_server.app_services import get_services
from local_asr_server.recordings import RecordingNotFound
from local_asr_server.server import create_app
from support import deterministic_settings


class MeetingLifecycleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings_patch = patch("local_asr_server.transcriptions.load_settings")
        self.settings_patch.start().return_value = deterministic_settings(
            self.root, recordings_dir=self.tmp.name,
        )
        self.app = create_app(
            default_model="test-model", recordings_dir=self.root, enable_auth=False,
        )
        self.client = TestClient(self.app)
        self.services = get_services(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.settings_patch.stop()
        self.tmp.cleanup()

    def _recorded(self, title: str) -> str:
        response = self.client.post(
            "/v1/recordings",
            json={"title": title, "mime_type": "audio/webm", "capture_mode": "mic_only"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        recording_id = response.json()["id"]
        response = self.client.post(f"/v1/recordings/{recording_id}/stop")
        self.assertEqual(response.status_code, 202, response.text)
        return recording_id

    def test_archive_persists_search_visibility_and_restore(self) -> None:
        recording_id = self._recorded("Private project zephyr")
        archived = self.client.post(f"/v1/meetings/{recording_id}/archive")
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertTrue(archived.json()["archived_at"])

        recent = self.client.get("/v1/meetings?limit=50")
        active = self.client.get("/v1/meetings?q=zephyr&limit=20")
        stored = self.client.get("/v1/meetings?q=zephyr&archived=true&limit=20")
        self.assertNotIn(recording_id, [r["id"] for r in recent.json()["items"]])
        self.assertEqual(active.json()["total"], 0)
        self.assertEqual([r["id"] for r in stored.json()["items"]], [recording_id])
        self.assertTrue(self.client.get(f"/v1/meetings/{recording_id}").json()["recording"]["archived_at"])

        # The source of truth is the recording metadata, not a transient UI flag.
        self.services.recordings.sync_catalog()
        self.assertEqual(
            self.client.get("/v1/meetings?q=zephyr&archived=true").json()["total"], 1,
        )
        restored = self.client.post(f"/v1/meetings/{recording_id}/restore")
        self.assertEqual(restored.status_code, 200)
        self.assertIsNone(restored.json()["archived_at"])
        self.assertEqual(self.client.get("/v1/meetings?q=zephyr").json()["total"], 1)
        self.assertEqual(self.client.get("/v1/meetings?q=zephyr&archived=true").json()["total"], 0)

    def test_delete_is_irreversible_only_after_archive_and_purges_exports(self) -> None:
        recording_id = self._recorded("Remove meeting")
        saved = self.services.transcriptions.save(
            {"text": "Sensitive local conversation", "segments": [], "model": "test"},
            recording_id=recording_id,
        )
        session = self.services.recordings.session_dir(recording_id)
        exports = self.services.transcriptions.root
        transcript_file = next(exports.glob(f"transcript_*_{saved['id'][:8]}.json"))
        self.assertTrue(transcript_file.exists())
        self.assertEqual(self.client.delete(f"/v1/meetings/{recording_id}").status_code, 409)
        self.assertEqual(self.client.post(f"/v1/meetings/{recording_id}/archive").status_code, 200)

        deleted = self.client.delete(f"/v1/meetings/{recording_id}")
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertFalse(session.exists())
        self.assertFalse(transcript_file.exists())
        self.assertFalse(transcript_file.with_suffix(".txt").exists())
        self.assertEqual(self.client.get(f"/v1/meetings/{recording_id}").status_code, 404)
        self.assertEqual(self.client.get("/v1/meetings?q=&archived=true").json()["total"], 0)
        with self.assertRaises(RecordingNotFound):
            self.services.recordings.get(recording_id)

        self.services.recordings.sync_catalog()
        self.services.transcriptions.sync()
        self.assertEqual(self.client.get("/v1/meetings?q=Remove").json()["total"], 0)
        self.assertEqual(self.client.get("/v1/meetings?q=Remove&archived=true").json()["total"], 0)
        self.assertEqual(self.client.get(f"/v1/transcriptions/{saved['id']}").status_code, 404)

    def test_merged_dependency_blocks_delete_without_corrupting_other_meetings(self) -> None:
        first_id = self._recorded("Original")
        second_id = self._recorded("Independent")
        first = self.services.transcriptions.save(
            {"text": "Original words", "segments": []}, recording_id=first_id,
        )
        merged = self.services.transcriptions.save(
            {
                "text": "Merged transcript",
                "segments": [],
                "merged_sources": [{"id": first["id"], "recording_id": first_id}],
            },
        )
        self.assertEqual(self.client.post(f"/v1/meetings/{first_id}/archive").status_code, 200)
        response = self.client.delete(f"/v1/meetings/{first_id}")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get(f"/v1/meetings/{second_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/v1/transcriptions/{merged['id']}").status_code, 200)
        self.assertTrue(self.services.recordings.session_dir(first_id).exists())

    def test_interrupted_staging_recovers_uncommitted_recording_and_exports(self) -> None:
        recording_id = self._recorded("Recover from interruption")
        saved = self.services.transcriptions.save(
            {"text": "Recoverable content", "segments": []}, recording_id=recording_id,
        )
        session = self.services.recordings.session_dir(recording_id)
        export_root = self.services.transcriptions.root
        export_file = next(export_root.glob(f"transcript_*_{saved['id'][:8]}.json"))
        stage = session.parent.parent / f".meeting-deleting-{recording_id}"
        export_stage = export_root / f".meeting-exports-deleting-{recording_id}"
        (session / ".meeting-deletion.json").write_text(
            json.dumps({"transcriptions_root": str(export_root)}), encoding="utf-8",
        )
        export_stage.mkdir()
        export_file.rename(export_stage / export_file.name)
        session.rename(stage)

        self.services.recordings._recover_interrupted_deletions()

        self.assertTrue(session.exists())
        self.assertTrue(export_file.exists())
        self.assertFalse(stage.exists())
        self.assertFalse(export_stage.exists())
        self.assertFalse((session / ".meeting-deletion.json").exists())
        self.assertEqual(self.client.get(f"/v1/meetings/{recording_id}").status_code, 200)

    def test_processing_or_capture_blocks_archive_and_delete(self) -> None:
        response = self.client.post(
            "/v1/recordings",
            json={"title": "Live meeting", "mime_type": "audio/webm", "capture_mode": "mic_only"},
        )
        recording_id = response.json()["id"]
        self.assertEqual(self.client.post(f"/v1/meetings/{recording_id}/archive").status_code, 409)
        self.assertEqual(self.client.delete(f"/v1/meetings/{recording_id}").status_code, 409)
        self.assertEqual(self.client.post(f"/v1/recordings/{recording_id}/stop").status_code, 202)
        job = self.services.jobs.create(
            job_id="active-delete-guard", job_type="transcription",
            scope_type="recording", scope_id=recording_id,
        )
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.client.post(f"/v1/meetings/{recording_id}/archive").status_code, 409)


if __name__ == "__main__":
    unittest.main()
