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


def _wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 16_000)
    return output.getvalue()


class DiarizationBenchmarkApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        settings = deterministic_settings(self.root, recordings_dir=str(self.root))
        self.patch_settings = patch("local_asr_server.transcriptions.load_settings", return_value=settings)
        self.patch_settings.start()
        self.app = create_app(
            default_model="test-model", recordings_dir=self.root, enable_auth=False,
        )
        # This is a deterministic source/API test; native/physical admission
        # is separately exercised on the Mac and in the arbiter's own tests.
        get_services(self.app).transcription_jobs._arbiter = None
        self.client = TestClient(self.app)
        self.store = get_services(self.app).recordings

    def tearDown(self):
        self.client.close()
        self.patch_settings.stop()
        self.tmp.cleanup()

    def recording(self, finalize=True):
        item = self.store.create(
            title="Private recording", mime_type="audio/wav", model="test-model",
            language="it", capture_mode="pc_only",
        )
        self.store.append_chunk(item["id"], 0, _wav())
        if finalize:
            self.store.finalize(item["id"])
        return item["id"]

    def test_validates_saved_recording_and_request_without_model_execution(self):
        recording_id = self.recording(finalize=False)
        url = f"/v1/recordings/{recording_id}/diarization-benchmarks"
        self.assertEqual(self.client.post(url, json={"engines": [
            "community-1", "nemotron3-fast128",
        ], "scope": "sample"}).status_code, 409)
        self.store.finalize(recording_id)
        self.assertEqual(self.client.post(url, json={"engines": [
            "community-1", "community-1",
        ]}).status_code, 422)
        self.assertEqual(self.client.post(url, json={"engines": [
            "community-1", "untrusted-remote",
        ]}).status_code, 422)
        self.assertEqual(self.client.get(f"/v1/recordings/not-a-uuid/diarization-benchmarks").status_code, 404)

    def test_job_api_persists_isolated_results_and_allows_lookup(self):
        recording_id = self.recording()
        url = f"/v1/recordings/{recording_id}/diarization-benchmarks"
        result = {
            "schema_version": 1, "scope": "sample", "track_id": "system",
            "preview_seconds": 1, "audio_seconds": 1, "reference_scored": False,
            "runs": [{"key": "community-1", "status": "completed", "preview": []}],
            "outcome_status": "completed",
        }
        with patch(
            "local_asr_server.routers.transcriptions.run_benchmark",
            return_value=result,
        ) as runner:
            response = self.client.post(url, json={
                "engines": ["community-1", "nemotron3-fast128"], "scope": "sample",
            })
            self.assertEqual(response.status_code, 202, response.text)
            job_id = response.json()["id"]
            stored = None
            for _ in range(100):
                stored = self.client.get(f"/v1/jobs/{job_id}").json()
                if stored["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.02)
            self.assertEqual(stored["status"], "completed", stored)
            runner.assert_called_once()
        listed = self.client.get(url)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["id"], job_id)
        self.assertEqual(listed.json()["items"][0]["result"]["track_id"], "system")
        self.assertNotIn("speaker_diarization", self.store.get(recording_id))
        self.assertEqual(self.store.get(recording_id)["title"], "Private recording")


if __name__ == "__main__":
    unittest.main()
