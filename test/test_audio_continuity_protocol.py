"""Deterministic source-event contract tests; not physical macOS evidence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from local_asr_server.recordings import RecordingStore
from local_asr_server.server import create_app
from unittest.mock import patch
from support import deterministic_settings


class AudioContinuityProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = RecordingStore(self.root, use_settings_dir=False)
        self.recording = self.store.create(
            title="Synthetic audio continuity", mime_type="audio/wav",
            model="test", language=None, capture_mode="both", capture_backend="native",
        )
        self.recording_id = self.recording["id"]
        self.store.mark_capture_started(self.recording_id, backend="native")

    def tearDown(self):
        self.temp.cleanup()

    def test_source_loss_and_restoration_keep_recording_live_and_mark_gap(self):
        events = [
            {"type": "ready", "recording_ready_uptime": 100.0},
            {"type": "source_interrupted", "source": "mic", "reason": "device_changed", "uptime": 105.0},
            {"type": "source_recovering", "source": "mic", "uptime": 105.1},
            {"type": "source_recovered", "source": "mic", "uptime": 105.5},
        ]
        for event in events:
            self.store.mark_capture_event(self.recording_id, event)
        meta = self.store.get(self.recording_id)
        self.assertEqual(meta["status"], "recording")
        self.assertEqual(meta["capture_status"], "recording")
        self.assertEqual(meta["timeline"]["source_health"]["mic"], "recovered")
        self.assertEqual(meta["timeline"]["source_interruptions"], [
            {"source": "mic", "start_ms": 5000, "end_ms": 5500}
        ])
        self.assertEqual(len(meta["timeline"]["events"]), len(events))
        self.store.mark_capture_event(self.recording_id, events[-1])
        self.assertEqual(len(self.store.get(self.recording_id)["timeline"]["events"]), len(events))

    def test_source_unavailable_is_not_capture_fatal(self):
        for event in [
            {"type": "ready", "recording_ready_uptime": 100.0},
            {"type": "source_interrupted", "source": "mic", "uptime": 101.0},
            {"type": "source_unavailable", "source": "mic", "uptime": 102.0},
        ]:
            self.store.mark_capture_event(self.recording_id, event)
        meta = self.store.get(self.recording_id)
        self.assertEqual(meta["capture_status"], "recording")
        self.assertEqual(meta["timeline"]["source_health"]["mic"], "unavailable")
        self.store.mark_capture_event(self.recording_id, {
            "type": "capture_fatal", "source": "backend", "reason": "storage_failed",
        })
        self.assertEqual(self.store.get(self.recording_id)["capture_status"], "error")

    def test_capture_sse_does_not_close_on_nonterminal_source_event(self):
        class FakeCapture:
            def __init__(self):
                self.events = [
                    {"type": "ready", "recording_ready_uptime": 100.0},
                    {"type": "source_interrupted", "source": "mic", "uptime": 102.0},
                    {"type": "source_recovered", "source": "mic", "uptime": 103.0},
                    {"type": "stopped"},
                ]

            def drain_events(self, _recording_id):
                items, self.events = self.events, []
                return items

            def get_session(self, _recording_id):
                return None

        settings = deterministic_settings(self.root, recordings_dir=str(self.root))
        with patch("local_asr_server.transcriptions.load_settings", return_value=settings):
            app = create_app(default_model="test-model", recordings_dir=self.root, enable_auth=False)
        fake = FakeCapture()
        app.state.capture_manager = fake
        with TestClient(app) as client:
            created = client.post("/v1/recordings", json={
                "title": "Synthetic SSE", "mime_type": "audio/wav",
                "capture_mode": "both", "capture_backend": "native",
            })
            self.assertEqual(created.status_code, 201)
            recording_id = created.json()["id"]
            app.state.recording_store.mark_capture_started(recording_id, backend="native")
            with client.stream("GET", f"/v1/recordings/{recording_id}/capture/events") as response:
                self.assertEqual(response.status_code, 200)
                received = [
                    json.loads(line.partition("data: ")[2]) for line in response.iter_lines()
                    if line.startswith("data: ")
                ]
        self.assertEqual([event["type"] for event in received], [
            "ready", "source_interrupted", "source_recovered", "stopped",
        ])
