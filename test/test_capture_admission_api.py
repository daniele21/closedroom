from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from local_asr_server.server import create_app
from support import deterministic_settings


class CaptureAdmissionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = deterministic_settings(
            Path(self.temp_dir.name),
            recordings_dir=self.temp_dir.name,
        )
        self.settings_patcher = patch(
            "local_asr_server.transcriptions.load_settings",
            return_value=self.settings,
        )
        self.settings_patcher.start()
        self.diarization_settings_patcher = patch(
            "local_asr_server.speaker_diarization.load_settings",
            return_value=self.settings,
        )
        self.diarization_settings_patcher.start()
        self.transcription_service_settings_patcher = patch(
            "local_asr_server.services.transcription_service.load_settings",
            return_value=self.settings,
        )
        self.transcription_service_settings_patcher.start()
        self.app = create_app(
            default_model="test-model",
            recordings_dir=Path(self.temp_dir.name),
            enable_auth=False,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.transcription_service_settings_patcher.stop()
        self.diarization_settings_patcher.stop()
        self.settings_patcher.stop()
        self.temp_dir.cleanup()

    def test_reservation_lifecycle_is_bounded_and_exclusive(self) -> None:
        created = self.client.post("/v1/capture/reservations")
        self.assertEqual(created.status_code, 202)
        payload = created.json()
        reservation_id = payload["reservation_id"]
        self.assertEqual(payload["status"], "granted")
        self.assertEqual(payload["active_workloads"], 0)

        conflict = self.client.post("/v1/capture/reservations")
        self.assertEqual(conflict.status_code, 409)

        current = self.client.get(f"/v1/capture/reservations/{reservation_id}")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["status"], "granted")

        released = self.client.delete(f"/v1/capture/reservations/{reservation_id}")
        self.assertEqual(released.status_code, 204)
        missing = self.client.get(f"/v1/capture/reservations/{reservation_id}")
        self.assertEqual(missing.status_code, 404)

    def test_busy_ai_then_capture_then_resume_keeps_queued_work(self) -> None:
        arbiter = self.app.state.heavy_workload_arbiter
        first_started = threading.Event()
        release_first = threading.Event()
        queued_started = threading.Event()

        def first() -> None:
            first_started.set()
            release_first.wait(timeout=2.0)

        arbiter.submit(task_id="active-ai", workload_type="analysis", run=first)
        self.assertTrue(first_started.wait(timeout=1.0))

        created = self.client.post("/v1/capture/reservations")
        self.assertEqual(created.status_code, 202)
        reservation_id = created.json()["reservation_id"]
        self.assertEqual(created.json()["status"], "waiting")

        arbiter.submit(
            task_id="queued-ai",
            workload_type="transcription",
            run=queued_started.set,
        )
        release_first.set()

        deadline = time.monotonic() + 1.0
        status = "waiting"
        while time.monotonic() < deadline:
            response = self.client.get(f"/v1/capture/reservations/{reservation_id}")
            self.assertEqual(response.status_code, 200)
            status = response.json()["status"]
            if status == "granted":
                break
            time.sleep(0.01)

        self.assertEqual(status, "granted")
        self.assertFalse(queued_started.wait(timeout=0.05))

        released = self.client.post(f"/v1/capture/reservations/{reservation_id}/release")
        self.assertEqual(released.status_code, 204)
        self.assertTrue(queued_started.wait(timeout=1.0))


if __name__ == "__main__":
    unittest.main()
