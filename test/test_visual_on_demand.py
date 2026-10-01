from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from local_asr_server.server import create_app
from local_asr_server.visual_intelligence.service import PostMeetingVisualService
from support import deterministic_settings


_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class VisualOnDemandApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = deterministic_settings(
            root,
            recordings_dir=self.temp_dir.name,
        )
        self.settings_patcher = patch(
            "local_asr_server.transcriptions.load_settings",
            return_value=self.settings,
        )
        self.settings_patcher.start()
        self.service_settings_patcher = patch(
            "local_asr_server.runtime.service_manager.load_settings",
            return_value=self.settings,
        )
        self.service_settings_patcher.start()
        self.app = create_app(
            default_model="test-model",
            recordings_dir=root,
            enable_auth=False,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.service_settings_patcher.stop()
        self.settings_patcher.stop()
        self.temp_dir.cleanup()

    def _create_recording(self, *, with_visual_frame: bool) -> str:
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Visual on demand",
                "mime_type": "audio/webm",
                "capture_mode": "pc_only",
            },
        )
        self.assertEqual(created.status_code, 201)
        recording_id = created.json()["id"]
        if with_visual_frame:
            uploaded = self.client.post(
                f"/v1/recordings/{recording_id}/visual-frames",
                data={"sequence": "0", "timestamp": "1.0"},
                files={"file": ("frame.jpg", b"\xff\xd8\xffjpeg", "image/jpeg")},
            )
            self.assertEqual(uploaded.status_code, 202)
        stopped = self.client.post(f"/v1/recordings/{recording_id}/stop")
        self.assertEqual(stopped.status_code, 202)
        return recording_id

    def _save_transcription(self, recording_id: str) -> dict:
        return self.app.state.transcription_store.save(
            {
                "recording_id": recording_id,
                "text": "Discussione di test",
                "segments": [
                    {"id": 0, "start": 0.0, "end": 1.0, "text": "Discussione di test"},
                ],
                "stats": {},
            },
            audio_filename="visual-on-demand",
            recording_id=recording_id,
        )

    def _wait_for_job(self, job_id: str) -> dict:
        deadline = time.time() + 2.0
        latest = {}
        while time.time() < deadline:
            response = self.client.get(f"/v1/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            latest = response.json()
            if latest.get("status") in _TERMINAL:
                return latest
            time.sleep(0.01)
        self.fail(f"visual job did not complete: {latest}")

    def test_job_requires_explicitly_captured_screen_context(self) -> None:
        recording_id = self._create_recording(with_visual_frame=False)
        self._save_transcription(recording_id)

        response = self.client.post(
            f"/v1/recordings/{recording_id}/visual-intelligence-jobs"
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("No screen context", response.json()["detail"])

    def test_job_enriches_existing_transcription_in_place_with_v2(self) -> None:
        recording_id = self._create_recording(with_visual_frame=True)
        saved = self._save_transcription(recording_id)
        process = Mock()

        def fake_process(services, received_recording_id, payload, **kwargs):
            self.assertEqual(received_recording_id, recording_id)
            self.assertEqual(payload["id"], saved["id"])
            self.assertTrue(kwargs["enabled"])
            self.assertEqual(kwargs["routing_mode"], "v2")
            self.assertTrue(callable(kwargs["cancel_requested"]))
            kwargs["progress_callback"]({"processed": 1, "total": 1})
            return {
                **payload,
                "stats": {
                    **(payload.get("stats") or {}),
                    "visual_intelligence": {
                        "version": 2,
                        "status": "completed",
                        "routing_mode": "v2",
                        "observation_count": 1,
                    },
                },
            }

        process.side_effect = fake_process
        with patch.object(self.app.state.transcription_service.visual, "process", process):
            created = self.client.post(
                f"/v1/recordings/{recording_id}/visual-intelligence-jobs"
            )
            self.assertEqual(created.status_code, 202)
            job = self._wait_for_job(created.json()["id"])

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["type"], "visual_intelligence")
        self.assertEqual(job["scope_type"], "transcription")
        self.assertEqual(job["scope_id"], saved["id"])
        persisted = self.app.state.transcription_store.get(saved["id"])
        self.assertEqual(persisted["id"], saved["id"])
        self.assertEqual(persisted["stats"]["visual_intelligence"]["version"], 2)
        self.assertEqual(persisted["stats"]["visual_intelligence"]["routing_mode"], "v2")
        self.assertNotIn("job_id", persisted)
        process.assert_called_once()


class StrictVisualRoutingTests(unittest.TestCase):
    def test_explicit_v2_router_failure_never_falls_back_to_legacy_inference(self) -> None:
        recordings = Mock()
        recordings.list_visual_frames.return_value = [
            {"sequence": 0, "timestamp": 0.0, "path": Path("unused.jpg")},
        ]
        runtime = Mock()
        services = SimpleNamespace(recordings=recordings, runtime=runtime)
        settings = {
            "visual_intelligence_enabled": False,
            "visual_routing_mode": "v1",
            "visual_llm_model": "qwen3-vl-4b",
            "visual_frame_similarity_threshold": 12,
        }

        with (
            patch(
                "local_asr_server.visual_intelligence.service.load_settings",
                return_value=settings,
            ),
            patch(
                "local_asr_server.visual_intelligence.service.TaskAwareFrameRouter.route",
                side_effect=RuntimeError("router exploded"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "visual_v2_router_failed"):
                PostMeetingVisualService().process(
                    services,
                    "recording-1",
                    {"segments": []},
                    enabled=True,
                    routing_mode="v2",
                )

        runtime.ensure_llm_ready.assert_not_called()
        recordings.reset_visual_observations.assert_not_called()


if __name__ == "__main__":
    unittest.main()
