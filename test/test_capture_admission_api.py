from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_overlay_backend_stop_releases_bound_capture_and_starts_queued_work(self) -> None:
        arbiter = self.app.state.heavy_workload_arbiter
        services = self.app.state.services
        recording = self.client.post('/v1/recordings', json={
            'title': 'Lease regression', 'mime_type': 'audio/wav', 'capture_backend': 'native',
        }).json()
        recording_id = recording['id']
        lease = self.client.post('/v1/capture/reservations').json()['reservation_id']
        ran = threading.Event()
        with patch.object(services.capture, 'start', return_value={'status': 'recording'}), \
             patch.object(services.capture, 'get_session', return_value=None):
            started = self.client.post(f'/v1/recordings/{recording_id}/capture/start', json={'reservation_id': lease})
        self.assertEqual(started.status_code, 202, started.text)
        arbiter.submit(task_id='waiting-asr', workload_type='transcription', run=ran.set)
        self.assertFalse(ran.wait(0.05))
        with patch.object(services.capture, 'stop', return_value={'events': []}), \
             patch.object(services.recordings, 'finalize', return_value=(recording, None)), \
             patch.object(arbiter, '_assert_admitted'), \
             patch.object(arbiter, '_admission_guard', None):
            stopped = self.client.post(f'/v1/recordings/{recording_id}/control/stop')
            self.assertEqual(stopped.status_code, 202, stopped.text)
            self.assertTrue(ran.wait(1.0))
        self.assertEqual(self.client.get(f'/v1/capture/reservations/{lease}').status_code, 404)

    def test_bound_lease_survives_failed_stop_and_cannot_be_released_by_another_run(self) -> None:
        arbiter = self.app.state.heavy_workload_arbiter
        lease = self.client.post('/v1/capture/reservations').json()['reservation_id']
        arbiter.bind_capture(lease, 'recording-one')
        self.assertFalse(arbiter.release_recording_capture('recording-two'))
        with patch.object(self.app.state.services.capture, 'stop', side_effect=RuntimeError('still capturing')):
            with self.assertRaises(RuntimeError):
                self.client.post('/v1/recordings/recording-one/capture/stop')
        self.assertTrue(arbiter.snapshot()['capture_reservation']['active'])
        self.assertTrue(arbiter.release_recording_capture('recording-one'))

    def test_finalization_failure_releases_terminated_native_capture(self) -> None:
        arbiter = self.app.state.heavy_workload_arbiter
        lease = self.client.post('/v1/capture/reservations').json()['reservation_id']
        arbiter.bind_capture(lease, 'recording-one')
        with patch.object(self.app.state.services.capture, 'stop', return_value={'events': []}), \
             patch.object(self.app.state.services.recordings, 'finalize', side_effect=RuntimeError('finalization failed')):
            with self.assertRaises(RuntimeError):
                self.client.post('/v1/recordings/recording-one/capture/stop')
        self.assertFalse(arbiter.snapshot()['capture_reservation']['active'])

    def test_activities_excludes_content_and_reports_capture_wait(self) -> None:
        self.app.state.services.jobs.create(job_id='activity-test', job_type='transcription', payload={'text': 'SECRET'})
        self.client.post('/v1/capture/reservations')
        response = self.client.get('/v1/activities')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['capture_blocked'])
        item = next(item for item in response.json()['items'] if item['id'] == 'activity-test')
        self.assertNotIn('payload', item)
        self.assertNotIn('result', item)
        self.assertNotIn('SECRET', response.text)

    def test_capture_cancel_preserves_audio_for_recovery_and_releases_lease(self) -> None:
        services = self.app.state.services
        recording = self.client.post('/v1/recordings', json={
            'title': 'Interrupted capture', 'mime_type': 'audio/wav',
            'capture_backend': 'native', 'capture_mode': 'mic_only',
        }).json()
        recording_id = recording['id']
        session_dir = services.recordings.session_dir(recording_id)
        audio = b'RIFF interrupted microphone audio'
        (session_dir / 'mic.wav').write_bytes(audio)
        reservation = self.client.post('/v1/capture/reservations').json()
        self.app.state.heavy_workload_arbiter.bind_capture(reservation['reservation_id'], recording_id)

        with patch.object(services.capture, 'cancel', return_value={'status': 'cancelled'}):
            response = self.client.post(f'/v1/recordings/{recording_id}/capture/cancel')

        self.assertEqual(response.status_code, 202)
        self.assertEqual((session_dir / 'mic.wav').read_bytes(), audio)
        saved = self.client.get(f'/v1/recordings/{recording_id}')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['status'], 'recoverable')
        self.assertEqual(saved.json()['capture_status'], 'stopped')
        self.assertFalse(self.app.state.heavy_workload_arbiter.snapshot()['capture_reservation']['active'])
        recovered = self.client.post(f'/v1/recordings/{recording_id}/recover')
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()['status'], 'recorded')
        self.assertEqual((session_dir / 'mic.wav').read_bytes(), audio)

    def test_empty_capture_cancel_keeps_interruption_diagnostics(self) -> None:
        services = self.app.state.services
        recording = self.client.post('/v1/recordings', json={
            'title': 'Empty interruption', 'mime_type': 'audio/wav',
            'capture_backend': 'native', 'capture_mode': 'mic_only',
        }).json()
        with patch.object(services.capture, 'cancel', return_value={'status': 'cancelled'}):
            response = self.client.post(f'/v1/recordings/{recording["id"]}/capture/cancel')
        self.assertEqual(response.status_code, 202)
        saved = self.client.get(f'/v1/recordings/{recording["id"]}')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['status'], 'interrupted')
        self.assertTrue(saved.json()['error'])

    def test_native_start_cannot_reuse_a_finalized_recording(self) -> None:
        services = self.app.state.services
        recording = self.client.post('/v1/recordings', json={
            'title': 'Saved original', 'mime_type': 'audio/wav',
            'capture_backend': 'native', 'capture_mode': 'mic_only',
        }).json()
        recording_id = recording['id']
        session_dir = services.recordings.session_dir(recording_id)
        (session_dir / 'mic.wav').write_bytes(b'original saved audio')
        services.recordings.finalize(recording_id)
        with patch.object(services.capture, 'start') as start:
            response = self.client.post(f'/v1/recordings/{recording_id}/capture/start', json={})
        self.assertEqual(response.status_code, 409)
        start.assert_not_called()
        self.assertEqual((session_dir / 'mic.wav').read_bytes(), b'original saved audio')

    def test_recovery_refuses_a_live_helper_even_after_an_error_event(self) -> None:
        services = self.app.state.services
        session = Mock(stopped=True)
        session.process.poll.return_value = None
        with patch.object(services.capture, 'get_session', return_value=session), \
             patch.object(services.recordings, 'recover') as recover:
            response = self.client.post('/v1/recordings/active-session/recover')
        self.assertEqual(response.status_code, 409)
        recover.assert_not_called()

    def test_capture_cancel_persists_error_and_is_safe_to_retry_after_recovery(self) -> None:
        services = self.app.state.services
        recording = self.client.post('/v1/recordings', json={
            'title': 'Retry interruption', 'mime_type': 'audio/wav',
            'capture_backend': 'native', 'capture_mode': 'mic_only',
        }).json()
        recording_id = recording['id']
        session_dir = services.recordings.session_dir(recording_id)
        (session_dir / 'mic.wav').write_bytes(b'partial audio')
        event = {'type': 'error', 'source': 'mic', 'message': 'Capture interrupted'}
        with patch.object(services.capture, 'cancel', return_value={'events': [event]}):
            self.assertEqual(self.client.post(f'/v1/recordings/{recording_id}/capture/cancel').status_code, 202)
        self.assertIn('Capture interrupted', services.recordings.get(recording_id)['warnings'])
        self.assertIn('Capture interrupted', (session_dir / 'timeline.json').read_text())
        self.assertEqual(self.client.post(f'/v1/recordings/{recording_id}/recover').status_code, 200)
        with patch.object(services.capture, 'cancel', return_value={'status': 'not_active'}):
            self.assertEqual(self.client.post(f'/v1/recordings/{recording_id}/capture/cancel').status_code, 202)
        self.assertEqual(services.recordings.get(recording_id)['status'], 'recorded')
        self.assertEqual((session_dir / 'mic.wav').read_bytes(), b'partial audio')

    def test_cancel_persistence_failure_releases_terminated_capture(self) -> None:
        services = self.app.state.services
        arbiter = self.app.state.heavy_workload_arbiter
        reservation = self.client.post('/v1/capture/reservations').json()
        arbiter.bind_capture(reservation['reservation_id'], 'recording-one')
        with patch.object(services.capture, 'cancel', return_value={}), \
             patch.object(services.recordings, 'interrupt_capture', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.client.post('/v1/recordings/recording-one/capture/cancel')
        self.assertFalse(arbiter.snapshot()['capture_reservation']['active'])


if __name__ == "__main__":
    unittest.main()
