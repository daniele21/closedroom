from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from local_asr_server.server import AudioRouter, create_app
from support import deterministic_settings


def _wav_bytes() -> bytes:
    path = Path(tempfile.gettempdir()) / "closedroom-test-tone.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes((b"\x00\x20" * 16_000))
    try:
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


class RecordingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.transcriptions_dir = Path(self.temp_dir.name) / "transcriptions"
        self.transcriptions_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(self.temp_dir.name) / "asr-cache"
        self.cache_patcher = patch("local_asr_server.transcriber.CACHE_DIR", self.cache_dir)
        self.cache_patcher.start()
        self.settings_patcher = patch("local_asr_server.transcriptions.load_settings")
        self.mock_load_settings = self.settings_patcher.start()
        self.mock_load_settings.return_value = deterministic_settings(
            Path(self.temp_dir.name),
            recordings_dir=self.temp_dir.name,
            default_condition_on_previous=True,
        )
        self.diarization_settings_patcher = patch(
            "local_asr_server.speaker_diarization.load_settings",
            return_value=self.mock_load_settings.return_value,
        )
        self.diarization_settings_patcher.start()
        self.transcription_service_settings_patcher = patch(
            "local_asr_server.services.transcription_service.load_settings",
            return_value=self.mock_load_settings.return_value,
        )
        self.transcription_service_settings_patcher.start()
        self.app = create_app(
            default_model="test-model",
            recordings_dir=Path(self.temp_dir.name),
            enable_auth=False,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.cache_patcher.stop()
        self.transcription_service_settings_patcher.stop()
        self.diarization_settings_patcher.stop()
        self.settings_patcher.stop()
        self.client.close()
        self.temp_dir.cleanup()

    def test_visual_frame_upload_is_staged_only_while_recording(self) -> None:
        created = self.client.post(
            "/v1/recordings",
            json={"title": "Visual call", "mime_type": "audio/webm", "capture_mode": "pc_only"},
        )
        recording_id = created.json()["id"]
        uploaded = self.client.post(
            f"/v1/recordings/{recording_id}/visual-frames",
            data={"sequence": "0", "timestamp": "1.25"},
            files={"file": ("frame.jpg", b"\xff\xd8\xffjpeg", "image/jpeg")},
        )
        self.assertEqual(uploaded.status_code, 202)
        self.assertEqual(uploaded.json()["sequence"], 0)
        listed = self.client.get(f"/v1/recordings/{recording_id}/visual-frames")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        frame = self.client.get(f"/v1/recordings/{recording_id}/visual-frames/0")
        self.assertEqual(frame.status_code, 200)
        self.assertEqual(frame.content, b"\xff\xd8\xffjpeg")
        self.client.post(f"/v1/recordings/{recording_id}/stop")
        rejected = self.client.post(
            f"/v1/recordings/{recording_id}/visual-frames",
            data={"sequence": "1", "timestamp": "2.0"},
            files={"file": ("frame.jpg", b"\xff\xd8\xffjpeg", "image/jpeg")},
        )
        self.assertEqual(rejected.status_code, 409)


    def test_manual_screenshot_api_persists_before_success_and_retry_is_idempotent(self) -> None:
        class FakeCaptureManager:
            def begin_screenshot(self, recording_id: str) -> None:
                return None

            def finish_screenshot(self, recording_id: str) -> None:
                return None

            def capture_screenshot(
                self,
                recording_id: str,
                *,
                request_id: str,
                display_id: int | None = None,
                admission_held: bool = False,
                original_path: Path | None = None,
                thumbnail_path: Path | None = None,
            ):
                self.assert_admission = admission_held
                assert original_path is not None
                assert thumbnail_path is not None
                original_path.write_bytes(b"\xff\xd8\xfforiginal")
                thumbnail_path.write_bytes(b"\xff\xd8\xffthumb")
                return {
                    "request_id": request_id,
                    "recording_id": recording_id,
                    "display_id": display_id or 7,
                    "display_title": "Screen 1",
                    "timestamp": 2.5,
                    "captured_uptime": 12.5,
                    "recording_ready_uptime": 10.0,
                    "captured_wall_time": 1000.0,
                    "width": 1920,
                    "height": 1080,
                    "thumbnail_width": 640,
                    "thumbnail_height": 360,
                    "format": "image/jpeg",
                    "overlay_exclusion": "closedroom_windows",
                }

        self.app.state.capture_manager = FakeCaptureManager()
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Screenshot call",
                "mime_type": "audio/wav",
                "capture_mode": "both",
                "capture_backend": "native",
            },
        )
        recording_id = created.json()["id"]

        first = self.client.post(
            f"/v1/recordings/{recording_id}/screenshots",
            json={"request_id": "request-1", "display_id": 7},
        )
        retry = self.client.post(
            f"/v1/recordings/{recording_id}/screenshots",
            json={"request_id": "request-1", "display_id": 7},
        )
        listed = self.client.get(f"/v1/recordings/{recording_id}/screenshots")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(first.json()["screenshot_id"], retry.json()["screenshot_id"])
        self.assertEqual(listed.json()["total"], 1)
        original = self.client.get(first.json()["original_url"])
        thumbnail = self.client.get(first.json()["thumbnail_url"])
        self.assertEqual(original.content, b"\xff\xd8\xfforiginal")
        self.assertEqual(thumbnail.content, b"\xff\xd8\xffthumb")

    def test_screenshot_display_selection_endpoint_updates_capture_owner(self) -> None:
        class FakeCaptureManager:
            def __init__(self) -> None:
                self.selected = None

            def set_screenshot_display(self, recording_id: str, display_id: int) -> dict:
                self.selected = (recording_id, display_id)
                return {
                    "recording_id": recording_id,
                    "display_id": display_id,
                    "display": {
                        "display_id": display_id,
                        "source_id": -display_id,
                        "title": "Screen 2",
                        "width": 2560,
                        "height": 1440,
                        "is_main": False,
                    },
                }

        fake = FakeCaptureManager()
        self.app.state.capture_manager = fake

        response = self.client.put(
            "/v1/recordings/rec-display-owner/screenshot-display",
            json={"display_id": 11},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_id"], 11)
        self.assertEqual(fake.selected, ("rec-display-owner", 11))


    def test_screenshot_failure_does_not_stop_or_mutate_recording(self) -> None:
        class FailingCaptureManager:
            def begin_screenshot(self, recording_id: str) -> None:
                return None

            def finish_screenshot(self, recording_id: str) -> None:
                return None

            def capture_screenshot(
                self,
                recording_id: str,
                *,
                request_id: str,
                display_id: int | None = None,
                admission_held: bool = False,
                original_path: Path | None = None,
                thumbnail_path: Path | None = None,
            ):
                raise RuntimeError("screen_capture_permission_required")

        self.app.state.capture_manager = FailingCaptureManager()
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Screenshot failure",
                "mime_type": "audio/wav",
                "capture_mode": "both",
                "capture_backend": "native",
            },
        )
        recording_id = created.json()["id"]

        response = self.client.post(
            f"/v1/recordings/{recording_id}/screenshots",
            json={"request_id": "request-fail", "display_id": 7},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("screen_capture_permission_required", response.json()["detail"])
        persisted = self.app.state.recording_store.get(recording_id)
        self.assertEqual(persisted["status"], "recording")
        self.assertEqual(persisted["screenshot_count"], 0)

    def test_visual_intelligence_v2_endpoint_preserves_v1_response(self) -> None:
        created = self.client.post(
            "/v1/recordings",
            json={"title": "Visual v2", "mime_type": "audio/webm", "capture_mode": "pc_only"},
        )
        recording_id = created.json()["id"]
        summary = {"version": 2, "status": "completed"}
        document = {
            "schema_version": 2, "observations": [], "speaker_intervals": [],
            "meeting_state_events": [], "share_sessions": [], "semantic_links": [],
            "routing_summary": {}, "model": "qwen", "prompt_version": 3,
        }
        self.app.state.recording_store.save_visual_intelligence(
            recording_id, [], summary, document=document,
        )

        legacy = self.client.get(f"/v1/recordings/{recording_id}/visual-intelligence")
        versioned = self.client.get(f"/v2/recordings/{recording_id}/visual-intelligence")

        self.assertEqual(legacy.status_code, 200)
        self.assertIn("observations", legacy.json())
        self.assertNotIn("schema_version", legacy.json())
        self.assertEqual(versioned.status_code, 200)
        self.assertEqual(versioned.json()["schema_version"], 2)
        persisted_document = versioned.json()["document"]
        self.assertEqual(
            {key: value for key, value in persisted_document.items() if key != "generation_id"},
            document,
        )
        self.assertEqual(
            persisted_document["generation_id"], versioned.json()["summary"]["generation_id"],
        )

        self.app.state.recording_store.replace_visual_intelligence_artifacts(
            recording_id, [{"sequence": 1}], {"version": 1, "status": "completed"},
        )
        legacy_after_v1 = self.client.get(f"/v1/recordings/{recording_id}/visual-intelligence")
        versioned_after_v1 = self.client.get(f"/v2/recordings/{recording_id}/visual-intelligence")

        self.assertEqual(legacy_after_v1.status_code, 200)
        self.assertNotIn("document", legacy_after_v1.json())
        self.assertNotIn("routing", legacy_after_v1.json())
        self.assertEqual(versioned_after_v1.status_code, 404)

    def test_source_server_marks_browser_overlay_fallback_as_expected(self) -> None:
        self.assertFalse(hasattr(self.app.state, "window_manager"))

        response = self.client.post(
            "/v1/system/window/overlay",
            json={"show": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["fallback"], "browser")
        self.assertTrue(response.json()["fallback_expected"])

    def test_ensure_capture_permissions_endpoint_delegates_to_manager(self) -> None:
        class FakeCaptureManager:
            def ensure_permissions(self, mode: str) -> dict:
                return {
                    "ok": mode == "pc_only",
                    "requested": False,
                    "permissions": {
                        "ok": mode == "pc_only",
                        "microphone": "notDetermined",
                        "screen_capture": "granted",
                        "modes": {
                            "mic_only": {"ok": False},
                            "pc_only": {"ok": True},
                            "both": {"ok": False},
                        },
                    },
                    "diagnostics": {
                        "bundle_identifier": "com.closedroom.nativecapture",
                        "code_signature": "signed",
                    },
                }

        self.app.state.capture_manager = FakeCaptureManager()

        response = self.client.post(
            "/v1/capture/ensure-permissions",
            json={"mode": "pc_only"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["permissions"]["modes"]["pc_only"]["ok"], True)

    @patch("local_asr_server.server.transcribe_file_sync")
    def test_stop_only_saves_audio_without_transcribing(self, transcribe) -> None:
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Call",
                "mime_type": "audio/webm;codecs=opus",
                "language": "it",
            },
        )
        self.assertEqual(created.status_code, 201)
        recording_id = created.json()["id"]

        chunk = self.client.post(
            f"/v1/recordings/{recording_id}/chunks",
            data={"sequence": "0"},
            files={"file": ("chunk.webm", b"audio-data", "audio/webm")},
        )
        self.assertEqual(chunk.status_code, 200)

        stopped = self.client.post(f"/v1/recordings/{recording_id}/stop")
        self.assertEqual(stopped.status_code, 202)
        self.assertEqual(stopped.json()["status"], "recorded")
        transcribe.assert_not_called()

        audio = self.client.get(f"/v1/recordings/{recording_id}/audio")
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.content, b"audio-data")
        transcribe.assert_not_called()

    def test_empty_recording_can_be_stopped(self) -> None:
        created = self.client.post(
            "/v1/recordings",
            json={"title": "Empty", "mime_type": "audio/webm"},
        )
        recording_id = created.json()["id"]

        stopped = self.client.post(f"/v1/recordings/{recording_id}/stop")

        self.assertEqual(stopped.status_code, 202)
        self.assertEqual(stopped.json()["status"], "recorded")

    def test_recording_project_does_not_attach_transcription_by_filename_only(self) -> None:
        self.app.state.transcription_store.save(
            {
                "text": "Trascrizione di un altro audio",
                "segments": [],
                "model": "test-model",
                "language": "it",
            },
            audio_filename="Untitled recording.webm",
        )
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Untitled recording",
                "mime_type": "audio/webm;codecs=opus",
                "language": "it",
                "capture_mode": "both",
            },
        )
        recording_id = created.json()["id"]

        response = self.client.get(f"/v1/recordings/{recording_id}/project")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["transcription"])

    @patch.object(AudioRouter, "route_to_multi_output")
    def test_create_recording_does_not_change_audio_route(self, route) -> None:
        created = self.client.post(
            "/v1/recordings",
            json={"title": "Call", "mime_type": "audio/webm"},
        )

        self.assertEqual(created.status_code, 201)
        route.assert_not_called()

    @patch.object(AudioRouter, "get_status")
    def test_audio_status_endpoint(self, get_status) -> None:
        get_status.return_value = {
            "ok": True,
            "platform": "darwin",
            "ready_to_record": True,
            "input_device": "MacBook Microphone",
            "output_device": "Local ASR Output - MacBook Speakers",
        }

        response = self.client.get("/v1/system/audio/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready_to_record"])

    @patch.object(AudioRouter, "get_status")
    @patch.object(AudioRouter, "route_to_multi_output", return_value=True)
    def test_audio_activate_endpoint(self, route, get_status) -> None:
        get_status.return_value = {
            "ok": True,
            "platform": "darwin",
            "ready_to_record": True,
            "input_device": "MacBook Microphone",
            "output_device": "Local ASR Output - MacBook Speakers",
        }

        response = self.client.post("/v1/system/audio/activate")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        route.assert_called_once_with()

    def test_protected_api_requires_local_session(self) -> None:
        app = create_app(
            default_model="test-model",
            recordings_dir=Path(self.temp_dir.name),
            enable_auth=True,
        )
        client = TestClient(app)
        try:
            unauthorized = client.post(
                "/v1/recordings",
                json={"title": "Call", "mime_type": "audio/webm"},
            )
            session = client.get("/v1/session")
            authorized = client.post(
                "/v1/recordings",
                json={"title": "Call", "mime_type": "audio/webm"},
            )

            self.assertEqual(unauthorized.status_code, 401)
            self.assertEqual(session.status_code, 200)
            self.assertTrue(session.json()["auth_enabled"])
            self.assertEqual(authorized.status_code, 201)
        finally:
            client.close()

    def test_capture_capabilities_endpoint_reports_fallback(self) -> None:
        response = self.client.get("/v1/capture/capabilities")

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["default_backend"], {"native", "browser"})
        self.assertIn("native", response.json())

    @patch("local_asr_server.server.transcribe_file_sync")
    def test_transcribe_recording_splits_tracks_and_merges_timeline(self, transcribe) -> None:
        transcribe.side_effect = [
            {
                "text": "Ciao",
                "language": "it",
                "segments": [{"id": 0, "start": 2.0, "end": 3.0, "text": "Ciao"}],
            },
            {
                "text": "Salve",
                "language": "it",
                "segments": [{"id": 0, "start": 1.0, "end": 1.5, "text": "Salve"}],
            },
        ]
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Call",
                "mime_type": "audio/webm;codecs=opus",
                "language": "it",
                "capture_mode": "both",
            },
        )
        recording_id = created.json()["id"]
        for track_id, content in {"mic": b"mic", "system": b"sys", "mixed": b"mix"}.items():
            response = self.client.post(
                f"/v1/recordings/{recording_id}/tracks/{track_id}/chunks",
                data={"sequence": "0"},
                files={"file": (f"{track_id}.webm", content, "audio/webm")},
            )
            self.assertEqual(response.status_code, 200)
        self.client.post(f"/v1/recordings/{recording_id}/stop")

        response = self.client.post(
            f"/v1/recordings/{recording_id}/transcriptions",
            json={"language": "it", "response_format": "verbose_json"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual([segment["speaker_label"] for segment in data["segments"]], ["Computer", "Tu"])
        self.assertIn("[00:01] Computer: Salve", data["text"])
        self.assertIn("[00:02] Tu: Ciao", data["text"])
        self.assertEqual({track["id"] for track in data["source_tracks"]}, {"mic", "system"})

    @patch("local_asr_server.routers.transcriptions.load_settings")
    @patch("local_asr_server.speechmatics_asr.SpeechmaticsBatchASRProvider.transcribe")
    def test_transcribe_recording_uses_speechmatics_for_each_track(self, transcribe, load_settings) -> None:
        load_settings.return_value = {
            **self.mock_load_settings.return_value,
            "asr_provider": "speechmatics",
            "speechmatics_api_key": "secret",
            "speechmatics_region": "eu",
            "speechmatics_model": "standard",
            "speechmatics_diarization": "speaker",
            "speechmatics_timeout_seconds": 30,
            "speechmatics_poll_interval_seconds": 1,
        }
        transcribe.side_effect = [
            {
                "text": "Mic",
                "language": "it",
                "model": "standard",
                "backend": "speechmatics-batch",
                "provider": "speechmatics",
                "metadata": {"speechmatics_diarization": "speaker", "provider_speaker": "S1"},
                "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": "Mic", "provider_speaker": "S1"}],
            },
            {
                "text": "System",
                "language": "it",
                "model": "standard",
                "backend": "speechmatics-batch",
                "provider": "speechmatics",
                "metadata": {"speechmatics_diarization": "speaker", "provider_speaker": "S2"},
                "segments": [{"id": 0, "start": 1.0, "end": 2.0, "text": "System", "provider_speaker": "S2"}],
            },
        ]
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Cloud Call",
                "mime_type": "audio/webm;codecs=opus",
                "language": "it",
                "capture_mode": "both",
            },
        )
        recording_id = created.json()["id"]
        for track_id, content in {"mic": b"mic", "system": b"sys", "mixed": b"mix"}.items():
            self.client.post(
                f"/v1/recordings/{recording_id}/tracks/{track_id}/chunks",
                data={"sequence": "0"},
                files={"file": (f"{track_id}.webm", content, "audio/webm")},
            )
        self.client.post(f"/v1/recordings/{recording_id}/stop")

        response = self.client.post(
            f"/v1/recordings/{recording_id}/transcriptions",
            json={"language": "it", "response_format": "verbose_json", "asr_provider": "speechmatics"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(data["asr_provider"], "speechmatics")
        self.assertEqual(data["backend"], "speechmatics-batch")
        self.assertEqual(data["model"], "standard")
        self.assertEqual(data["provider_options"]["speechmatics_model"], "standard")
        self.assertEqual(data["stats"]["model"], "standard")
        self.assertEqual(data["stats"]["asr_provider"], "speechmatics")
        self.assertEqual({track["id"] for track in data["source_tracks"]}, {"mic", "system"})
        self.assertNotIn("secret", str(data))

    @patch("local_asr_server.server.transcribe_file_sync")
    def test_transcribe_recording_saves_audio_intelligence_shadow_metadata(self, transcribe) -> None:
        transcribe.side_effect = [
            {
                "text": "Ciao",
                "language": "it",
                "segments": [{"id": 0, "start": 0.1, "end": 0.8, "text": "Ciao"}],
            },
            {
                "text": "Salve",
                "language": "it",
                "segments": [{"id": 0, "start": 0.2, "end": 0.9, "text": "Salve"}],
            },
        ]
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Native Call",
                "mime_type": "audio/wav",
                "language": "it",
                "capture_mode": "both",
                "capture_backend": "native",
            },
        )
        recording_id = created.json()["id"]
        wav_content = _wav_bytes()
        for track_id in ["mic", "system", "mixed"]:
            response = self.client.post(
                f"/v1/recordings/{recording_id}/tracks/{track_id}/chunks",
                data={"sequence": "0"},
                files={"file": (f"{track_id}.wav", wav_content, "audio/wav")},
            )
            self.assertEqual(response.status_code, 200)
        self.client.post(f"/v1/recordings/{recording_id}/stop")

        response = self.client.post(
            f"/v1/recordings/{recording_id}/transcriptions",
            json={"language": "it", "response_format": "verbose_json"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["stats"]["audio_intelligence"]["enabled"])
        self.assertTrue(data["stats"]["audio_intelligence"]["mock_insights"])
        self.assertIn("channel", data["segments"][0])
        self.assertIn("speech_rate_wpm", data["segments"][0])

        intelligence = self.client.get(f"/v1/recordings/{recording_id}/intelligence")
        self.assertEqual(intelligence.status_code, 200)
        self.assertIn(intelligence.json()["backend"], {"silero-vad-v4", "energy-rms-v1"})
        self.assertTrue(intelligence.json()["mock"])

        saved = self.app.state.transcription_store.get(data["saved_id"])
        self.assertIsNone(saved.get("analysis"))

    @patch("local_asr_server.server.transcribe_file_sync")
    def test_transcription_job_for_recording(self, transcribe) -> None:
        self.mock_load_settings.return_value["visual_intelligence_enabled"] = True
        transcribe.return_value = {
            "text": "Ciao",
            "language": "it",
            "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": "Ciao"}],
        }
        created = self.client.post(
            "/v1/recordings",
            json={"title": "Call", "mime_type": "audio/webm;codecs=opus", "capture_mode": "mic_only"},
        )
        recording_id = created.json()["id"]
        self.client.post(
            f"/v1/recordings/{recording_id}/tracks/mic/chunks",
            data={"sequence": "0"},
            files={"file": ("mic.webm", b"mic", "audio/webm")},
        )
        self.client.post(f"/v1/recordings/{recording_id}/stop")

        job = self.client.post(
            f"/v1/recordings/{recording_id}/transcription-jobs",
            json={
                "language": "it",
                "response_format": "verbose_json",
                "visual_intelligence_enabled": False,
            },
        )
        self.assertEqual(job.status_code, 202)
        job_id = job.json()["id"]

        statuses = []
        for _ in range(50):
            status = self.client.get(f"/v1/jobs/{job_id}").json()
            statuses.append(status["status"])
            if status["status"] == "completed":
                break
            import time
            time.sleep(0.05)

        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["result"]["text"], "[00:00] Tu: Ciao")
        self.assertEqual(status["result"]["stats"]["speaker_diarization"]["status"], "disabled")
        self.assertIn(status["result"]["outcome_status"], {"completed", "completed_with_warnings"})
        self.assertIn("diagnostics", status["result"])
        events = self.app.state.job_store.events_after(job_id, 0)
        steps = [event["current_step"] for event in events]
        self.assertIn("diarizing", steps)
        self.assertNotIn("visual_processing", steps)
        stored_job = self.app.state.job_store.get(job_id)
        self.assertFalse(stored_job["payload"]["visual_intelligence_enabled"])
        self.assertIn("audio_intelligence", steps)
        self.assertIn("saving", steps)
        completed_event = next(event for event in reversed(events) if event["status"] == "completed")
        self.assertEqual(
            completed_event["payload"]["outcome_status"],
            status["result"]["outcome_status"],
        )

        diagnostics = self.client.get(f"/v1/meetings/{recording_id}/diagnostics")
        self.assertEqual(diagnostics.status_code, 200)
        self.assertEqual(diagnostics.json()["outcome_status"], status["result"]["outcome_status"])
        self.assertTrue(diagnostics.json()["diagnostics"])

    @patch(
        "local_asr_server.transcription_diarization.TranscriptionDiarizationService.process_audio_payload"
    )
    @patch("local_asr_server.server.transcribe_file_sync")
    def test_initial_speechmatics_diarization_is_independent_from_local_asr(
        self,
        transcribe,
        diarize,
    ) -> None:
        transcribe.return_value = {
            "text": "Uno due",
            "language": "it",
            "segments": [
                {"id": 0, "start": 0.0, "end": 0.5, "text": "Uno"},
                {"id": 1, "start": 0.5, "end": 1.0, "text": "due"},
            ],
        }

        def diarization_result(_path, payload, **_kwargs):
            segments = [dict(item) for item in payload["segments"]]
            segments[0]["provider_speaker"] = "system:S1"
            segments[1]["provider_speaker"] = "system:S2"
            return {
                **payload,
                "segments": segments,
                "stats": {
                    "speaker_diarization": {
                        "status": "completed",
                        "engine": "speechmatics-batch-diarization",
                        "provider": "speechmatics",
                        "assigned_segments": 2,
                        "clusters_by_track": {"system": ["system:S1", "system:S2"]},
                    }
                },
            }

        diarize.side_effect = diarization_result
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Cloud diarization",
                "mime_type": "audio/wav",
                "capture_mode": "pc_only",
            },
        )
        recording_id = created.json()["id"]
        self.client.post(
            f"/v1/recordings/{recording_id}/tracks/system/chunks",
            data={"sequence": "0"},
            files={"file": ("system.wav", _wav_bytes(), "audio/wav")},
        )
        self.client.post(f"/v1/recordings/{recording_id}/stop")

        response = self.client.post(
            f"/v1/recordings/{recording_id}/transcriptions",
            json={
                "language": "it",
                "asr_provider": "local",
                "diarization_provider": "speechmatics",
                "speechmatics_region": "eu",
                "speechmatics_model": "standard",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(transcribe.call_count, 1)
        self.assertEqual(diarize.call_count, 1)
        self.assertEqual(diarize.call_args.kwargs["provider"], "speechmatics")
        self.assertEqual(response.json()["stats"]["speaker_diarization"]["provider"], "speechmatics")

    def test_diarization_job_updates_existing_transcription_without_transcribing(self) -> None:
        created = self.client.post(
            "/v1/recordings",
            json={"title": "Call", "mime_type": "audio/wav", "capture_mode": "mic_only"},
        )
        recording_id = created.json()["id"]
        saved = self.app.state.transcription_store.save(
            {
                "text": "[00:00] Tu: Ciao",
                "language": "it",
                "segments": [{
                    "id": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Ciao",
                    "track_id": "mic",
                    "source": "mic",
                    "speaker_label": "Tu",
                }],
            },
            audio_filename="Call",
            recording_id=recording_id,
        )

        class FakeDiarizationService:
            def run(self, recording_store, transcription_store, transcription_id, **kwargs):
                kwargs["progress_callback"]("diarizing_system", 60, {"provider": kwargs["provider"]})
                result = transcription_store.get(transcription_id)
                result["stats"]["speaker_diarization"] = {
                    "status": "completed",
                    "provider": kwargs["provider"],
                    "cluster_count": 1,
                }
                return result

        self.app.state.diarization_service = FakeDiarizationService()
        response = self.client.post(
            f"/v1/transcriptions/{saved['id']}/diarization-jobs",
            json={"provider": "local"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["type"], "diarization")
        self.assertEqual(response.json()["scope_type"], "transcription")

        job_id = response.json()["id"]
        for _ in range(50):
            status = self.client.get(f"/v1/jobs/{job_id}").json()
            if status["status"] == "completed":
                break
            import time
            time.sleep(0.02)

        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["result"]["text"], "[00:00] Tu: Ciao")
        self.assertEqual(status["result"]["stats"]["speaker_diarization"]["provider"], "local")
        stored = self.app.state.job_store.get(job_id)
        self.assertEqual(stored["type"], "diarization")
        self.assertEqual(stored["payload"]["transcription_id"], saved["id"])

    def test_active_recording_and_overlay_flow(self) -> None:
        # 1. Initially active is False
        res = self.client.get("/v1/recordings/active")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["active"])

        # 2. Create a recording
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Test Active Flow",
                "mime_type": "audio/webm",
                "capture_backend": "browser",
            },
        )
        self.assertEqual(created.status_code, 201)
        recording_id = created.json()["id"]

        # 3. Check active recording details
        res = self.client.get("/v1/recordings/active")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["active"])
        self.assertEqual(res.json()["recording_id"], recording_id)
        self.assertEqual(res.json()["capture_backend"], "browser")

        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "recording")
        self.assertEqual(health.json()["app_version"], "0.1.0")
        from local_asr_server.app_identity import get_app_identity
        self.assertEqual(health.json()["bundle_identifier"], get_app_identity().bundle_identifier)
        self.assertIn("bundle_display_name", health.json())

        # 4. Append chunk and verify bytes_written changes
        chunk = self.client.post(
            f"/v1/recordings/{recording_id}/chunks",
            data={"sequence": "0"},
            files={"file": ("chunk.webm", b"audio-data", "audio/webm")},
        )
        self.assertEqual(chunk.status_code, 200)

        res = self.client.get("/v1/recordings/active")
        self.assertEqual(res.json()["bytes_written"], len(b"audio-data"))

        # 5. Connect to SSE events endpoint is not called here to prevent blocking/hanging in synchronous tests.

        # 6. Stop via unified control endpoint
        stopped = self.client.post(f"/v1/recordings/{recording_id}/control/stop")
        self.assertEqual(stopped.status_code, 202)

        # 7. Verify active is False again
        res = self.client.get("/v1/recordings/active")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["active"])

    def test_control_stop_unknown_recording_returns_404(self) -> None:
        res = self.client.post("/v1/recordings/non-existent-recording-id/control/stop")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["detail"], "Recording not found")

    def test_client_log_endpoint_records_events(self) -> None:
        res = self.client.post(
            "/v1/system/client-log",
            json={
                "level": "info",
                "source": "overlay",
                "message": "Overlay test event",
                "data": {"count": 1},
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("success"))


    def test_screenshot_api_uses_store_owned_staging_and_is_idempotent(self) -> None:
        created = self.client.post(
            "/v1/recordings",
            json={
                "title": "Screenshot API",
                "mime_type": "audio/wav",
                "language": "it",
                "capture_mode": "both",
                "capture_backend": "native",
            },
        )
        self.assertEqual(created.status_code, 201)
        recording_id = created.json()["id"]

        class FakeCapture:
            def __init__(self) -> None:
                self.calls = 0

            def begin_screenshot(self, _recording_id: str) -> None:
                return None

            def finish_screenshot(self, _recording_id: str) -> None:
                return None

            def capture_screenshot(
                self,
                _recording_id: str,
                *,
                request_id: str,
                display_id: int | None,
                admission_held: bool,
                original_path: Path,
                thumbnail_path: Path,
            ) -> dict:
                self.calls += 1
                self.last_paths = (original_path, thumbnail_path)
                original_path.write_bytes(b"\xff\xd8\xfforiginal")
                thumbnail_path.write_bytes(b"\xff\xd8\xffthumb")
                return {
                    "request_id": request_id,
                    "display_id": display_id or 7,
                    "display_title": "Screen 1",
                    "captured_uptime": 12.5,
                    "captured_wall_time": 1000.0,
                    "recording_ready_uptime": 10.0,
                    "timestamp": 2.5,
                    "width": 1920,
                    "height": 1080,
                    "thumbnail_width": 640,
                    "thumbnail_height": 360,
                    "overlay_exclusion": "closedroom_applications",
                    "capture_ms": 80,
                    "encode_ms": 20,
                    "write_ms": 5,
                    "roundtrip_ms": 120,
                    "worker_restart_count": 0,
                }

        fake = FakeCapture()
        self.app.state.capture_manager = fake
        body = {"request_id": "api-shot-1", "display_id": 7}

        first = self.client.post(
            f"/v1/recordings/{recording_id}/screenshots",
            json=body,
        )
        second = self.client.post(
            f"/v1/recordings/{recording_id}/screenshots",
            json=body,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(
            first.json()["screenshot_id"],
            second.json()["screenshot_id"],
        )
        self.assertEqual(first.json()["capture_ms"], 80)
        self.assertEqual(first.json()["roundtrip_ms"], 120)
        self.assertFalse(fake.last_paths[0].exists())
        self.assertFalse(fake.last_paths[1].exists())

if __name__ == "__main__":
    unittest.main()