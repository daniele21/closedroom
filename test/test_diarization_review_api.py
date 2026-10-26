from __future__ import annotations

import io
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from local_asr_server.server import create_app
from local_asr_server.app_services import get_services
from support import deterministic_settings


def wav_bytes() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 16_000)
    return out.getvalue()


class ReviewedDiarizationApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        settings = deterministic_settings(self.root, recordings_dir=str(self.root))
        self.patch_settings = patch(
            "local_asr_server.transcriptions.load_settings", return_value=settings,
        )
        self.patch_review = patch(
            "local_asr_server.transcription_diarization_review.load_settings",
            return_value={"speaker_diarization_minimum_overlap": 0.25},
        )
        self.patch_settings.start()
        self.patch_review.start()
        self.app = create_app(default_model="test-model", recordings_dir=self.root, enable_auth=False)
        self.services = get_services(self.app)
        self.services.transcription_jobs._arbiter = None
        self.client = TestClient(self.app)
        recording = self.services.recordings.create(
            title="Sensitive meeting", mime_type="audio/wav", model="test-model",
            language="en", capture_mode="pc_only",
        )
        self.recording_id = recording["id"]
        self.services.recordings.append_track_chunk(self.recording_id, "system", 0, wav_bytes())
        self.services.recordings.finalize(self.recording_id)
        self.original = self.services.transcriptions.save({
            "text": "Fixed original text.",
            "segments": [
                {"id": 0, "start": 0.0, "end": 0.8, "text": "Fixed original text.",
                 "track_id": "system", "speaker_label": "Old label"},
            ],
            "source_tracks": [{"id": "system", "label": "Computer"}],
            "stats": {},
        }, recording_id=self.recording_id)
        self.id = self.original["id"]
        self.path = f"/v1/transcriptions/{self.id}/diarization-reviews"

    def tearDown(self):
        self.client.close()
        self.patch_review.stop()
        self.patch_settings.stop()
        self.tmp.cleanup()

    def _review_job(self):
        result = {
            "scope": "full", "track_id": "system", "audio_seconds": 1,
            "runs": [{
                "key": "community-1", "status": "completed", "engine": "fluidaudio-community-1",
                "timeline": [{"speaker": "S1", "start": 0, "end": 0.8}],
            }],
            "outcome_status": "completed",
        }
        with patch("local_asr_server.routers.transcriptions.run_benchmark",
                   return_value=result) as runner:
            response = self.client.post(self.path)
            self.assertEqual(response.status_code, 202, response.text)
            job_id = response.json()["id"]
            job = {}
            for _ in range(150):
                job = self.client.get(f"/v1/jobs/{job_id}").json()
                if job.get("status") in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.02)
            self.assertEqual(job["status"], "completed", job)
            runner.assert_called_once()
            self.assertEqual(runner.call_args.kwargs["engines"], ["community-1"])
            self.assertEqual(runner.call_args.kwargs["scope"], "full")
        return job_id

    def test_preview_confirmation_undo_are_scoped_and_non_destructive(self):
        before = self.services.transcriptions.get(self.id)
        job_id = self._review_job()
        self.assertNotIn("timeline", self.client.get(f"/v1/jobs/{job_id}").json()["result"]["runs"][0])
        self.assertEqual(self.client.get(self.path).json()["undo"], None)
        self.assertEqual(self.services.transcriptions.get(self.id), before)
        preview_url = f"{self.path}/{job_id}/preview"
        preview = self.client.get(preview_url)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["assigned_segments"], 1)
        self.assertNotIn("candidate", preview.json())
        self.assertEqual(self.services.transcriptions.get(self.id), before)

        response = self.client.post(f"{self.path}/{job_id}/apply")
        self.assertEqual(response.status_code, 200, response.text)
        applied = response.json()
        self.assertEqual(applied["transcription"]["text"], before["text"])
        self.assertEqual(
            [(s["start"], s["end"], s["text"]) for s in applied["transcription"]["segments"]],
            [(s["start"], s["end"], s["text"]) for s in before["segments"]],
        )
        self.assertEqual(applied["transcription"]["segments"][0]["provider_speaker"], "system:S1")
        self.assertEqual(self.client.get(self.path).json()["undo"]["revision_id"], applied["revision_id"])
        self.assertEqual(self.client.post(f"{self.path}/{job_id}/apply").status_code, 409)
        restored = self.client.post(f"{self.path}/undo", json={"revision_id": applied["revision_id"]})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["transcription"]["text"], before["text"])
        self.assertEqual(self.client.get(self.path).json()["undo"], None)

    def test_cross_transcription_review_reference_is_rejected(self):
        job_id = self._review_job()
        other = self.services.transcriptions.save({
            "text": "Other", "segments": [{"start": 0, "end": 1, "text": "Other"}],
            "stats": {},
        }, recording_id=self.recording_id)
        wrong = f"/v1/transcriptions/{other['id']}/diarization-reviews/{job_id}"
        self.assertEqual(self.client.get(f"{wrong}/preview").status_code, 404)
        self.assertEqual(self.client.post(f"{wrong}/apply").status_code, 404)


if __name__ == "__main__":
    unittest.main()
