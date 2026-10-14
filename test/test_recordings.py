from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from local_asr_server.recordings import RecordingConflict, RecordingNotFound, RecordingStore


class RecordingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = RecordingStore(self.root, use_settings_dir=False)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create_recording(self) -> dict:
        return self.store.create(
            title="Titolo Registrazione",
            mime_type="audio/webm;codecs=opus",
            model="test-model",
            language="it",
        )

    def test_import_audio_is_published_durably_without_active_capture(self) -> None:
        source = b"audio bytes" * 128
        created = self.store.import_audio(
            io.BytesIO(source), filename="meeting.mp3",
            model="test-model", language="it",
        )
        self.assertEqual(created["status"], "recorded")
        self.assertEqual(created["capture_backend"], "import")
        self.assertEqual(created["capture_status"], "stopped")
        self.assertIsNone(self.store.active_recording())
        self.assertEqual(self.store.audio_path(created["id"]).read_bytes(), source)
        tracks = self.store.transcribable_tracks(created["id"])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0][0]["source"], "mixed")
        self.assertEqual(tracks[0][0]["chunks"][0]["sha256"], hashlib.sha256(source).hexdigest())
        reopened = RecordingStore(self.root, use_settings_dir=False)
        self.assertEqual(reopened.get(created["id"])["status"], "recorded")
        self.assertEqual(reopened.audio_path(created["id"]).read_bytes(), source)

    def test_import_request_is_idempotent_even_after_restart(self) -> None:
        data = b"meeting audio"
        first = self.store.import_audio(
            io.BytesIO(data), filename="meeting.wav", title="Imported call",
            model="test-model", request_id="import-001",
        )
        restarted = RecordingStore(self.root, use_settings_dir=False)
        second = restarted.import_audio(
            io.BytesIO(data), filename="meeting.wav", title="Imported call",
            model="test-model", request_id="import-001",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(restarted.list()), 1)
        with self.assertRaisesRegex(RecordingConflict, "different audio or options"):
            restarted.import_audio(
                io.BytesIO(b"other"), filename="meeting.wav",
                title="Imported call", model="test-model", request_id="import-001",
            )
        self.assertEqual(len(restarted.list()), 1)

    def test_failed_import_cleans_staging_and_keeps_no_recording(self) -> None:
        from local_asr_server.recordings import MAX_IMPORTED_AUDIO_BYTES

        with self.assertRaisesRegex(RecordingConflict, "empty"):
            self.store.import_audio(io.BytesIO(b""), filename="empty.wav", model="test")
        with self.assertRaisesRegex(RecordingConflict, "Unsupported"):
            self.store.import_audio(io.BytesIO(b"data"), filename="../not-audio.exe", model="test")

        class SizeOverrunStream:
            def read(self, _size):
                return b"oversized"

        # A low test limit exercises the actual bounded-copy path, not only
        # the early Content-Length check in the API.
        with patch("local_asr_server.recordings.MAX_IMPORTED_AUDIO_BYTES", 3):
            with self.assertRaisesRegex(RecordingConflict, "maximum size"):
                self.store.import_audio(SizeOverrunStream(), filename="too-big.wav", model="test")
        self.assertEqual(self.store.list(), [])
        self.assertEqual(list(self.root.glob("*/.import-*")), [])

    def test_startup_discards_only_interrupted_import_staging(self) -> None:
        date_dir = self.root / "2026-10-14"
        interrupted = date_dir / ".import-crashed"
        interrupted.mkdir(parents=True)
        (interrupted / "recording.wav").write_bytes(b"partial")
        valid = self.store.import_audio(
            io.BytesIO(b"valid"), filename="normal.wav", model="test-model",
        )
        reopened = RecordingStore(self.root, use_settings_dir=False)
        self.assertFalse(interrupted.exists())
        self.assertEqual(reopened.audio_path(valid["id"]).read_bytes(), b"valid")

    def test_atomic_json_writes_use_independent_temporary_files(self) -> None:
        target = self.root / "state.json"
        errors = []

        def write(index: int) -> None:
            try:
                self.store._write_json_atomic(target, {"index": index})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertIn(json.loads(target.read_text())["index"], range(12))
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_persists_chunks_in_order_and_finalizes_audio(self) -> None:
        recording = self.create_recording()

        first = self.store.append_chunk(recording["id"], 0, b"first")
        second = self.store.append_chunk(recording["id"], 1, b"second")
        finalized, should_start = self.store.finalize(recording["id"])

        self.assertEqual(first["chunk_count"], 1)
        self.assertEqual(second["bytes_written"], 11)
        self.assertEqual(finalized["status"], "recorded")
        self.assertFalse(should_start)
        self.assertEqual(self.store.audio_path(recording["id"]).read_bytes(), b"firstsecond")

    def test_finalized_track_hash_is_persisted_and_reused(self) -> None:
        recording = self.create_recording()
        self.store.append_chunk(recording["id"], 0, b"first")
        self.store.append_chunk(recording["id"], 1, b"second")
        self.store.finalize(recording["id"])

        expected = hashlib.sha256(b"firstsecond").hexdigest()
        first = self.store.track_content_sha256(recording["id"], "mixed")
        with patch(
            "local_asr_server.recordings._sha256_path",
            side_effect=AssertionError("persisted track hash should avoid rescanning audio"),
        ):
            second = self.store.track_content_sha256(recording["id"], "mixed")

        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        public_track = self.store.get(recording["id"], include_result=False)["audio_tracks"][0]
        self.assertNotIn("_content_sha256", public_track)

    def test_persisted_track_hash_invalidates_if_audio_changes(self) -> None:
        recording = self.create_recording()
        self.store.append_chunk(recording["id"], 0, b"audio")
        self.store.finalize(recording["id"])
        first = self.store.track_content_sha256(recording["id"], "mixed")

        self.store.audio_path(recording["id"]).write_bytes(b"changed-audio")
        second = self.store.track_content_sha256(recording["id"], "mixed")

        self.assertNotEqual(first, second)
        self.assertEqual(second, hashlib.sha256(b"changed-audio").hexdigest())

    def test_rejects_out_of_order_and_post_stop_chunks(self) -> None:
        recording = self.create_recording()

        with self.assertRaises(RecordingConflict):
            self.store.append_chunk(recording["id"], 1, b"wrong")

        self.store.append_chunk(recording["id"], 0, b"audio")
        self.store.finalize(recording["id"])

        with self.assertRaises(RecordingConflict):
            self.store.append_chunk(recording["id"], 1, b"late")

    def test_duplicate_chunk_with_same_content_is_idempotent(self) -> None:
        recording = self.create_recording()

        first = self.store.append_chunk(recording["id"], 0, b"audio")
        duplicate = self.store.append_chunk(recording["id"], 0, b"audio")
        finalized, _ = self.store.finalize(recording["id"])

        self.assertEqual(first["chunk_count"], 1)
        self.assertEqual(duplicate["chunk_count"], 1)
        self.assertEqual(finalized["bytes_written"], 5)
        self.assertEqual(self.store.audio_path(recording["id"]).read_bytes(), b"audio")

    def test_duplicate_chunk_with_different_content_is_rejected(self) -> None:
        recording = self.create_recording()

        self.store.append_chunk(recording["id"], 0, b"audio")

        with self.assertRaises(RecordingConflict):
            self.store.append_chunk(recording["id"], 0, b"other")

    def test_stop_is_idempotent(self) -> None:
        recording = self.create_recording()
        self.store.append_chunk(recording["id"], 0, b"audio")

        _, first_should_start = self.store.finalize(recording["id"])
        metadata, second_should_start = self.store.finalize(recording["id"])

        self.assertFalse(first_should_start)
        self.assertFalse(second_should_start)
        self.assertEqual(metadata["status"], "recorded")

    def test_recorded_audio_survives_restart(self) -> None:
        recording = self.create_recording()
        self.store.append_chunk(recording["id"], 0, b"audio")
        self.store.finalize(recording["id"])

        restored = RecordingStore(self.root, use_settings_dir=False).get(recording["id"])

        self.assertEqual(restored["status"], "recorded")
        self.assertEqual(self.store.audio_path(recording["id"]).read_bytes(), b"audio")

    def test_interrupted_recording_with_part_file_is_recoverable_after_restart(self) -> None:
        recording = self.create_recording()
        self.store.append_chunk(recording["id"], 0, b"audio")

        restarted = RecordingStore(self.root, use_settings_dir=False)
        restored = restarted.get(recording["id"])
        recovered = restarted.recover(recording["id"])

        self.assertEqual(restored["status"], "recoverable")
        self.assertEqual(recovered["status"], "recorded")
        self.assertTrue(recovered["partial"])
        self.assertEqual(restarted.audio_path(recording["id"]).read_bytes(), b"audio")

    def test_interrupted_empty_recording_can_be_discarded(self) -> None:
        recording = self.create_recording()

        restarted = RecordingStore(self.root, use_settings_dir=False)
        restored = restarted.get(recording["id"])
        restarted.discard(recording["id"])

        self.assertEqual(restored["status"], "interrupted")
        with self.assertRaises(RecordingNotFound):
            restarted.get(recording["id"])

    def test_split_tracks_are_persisted_under_one_recording(self) -> None:
        recording = self.store.create(
            title="Call",
            mime_type="audio/webm;codecs=opus",
            model="test-model",
            language="it",
            capture_mode="both",
        )

        self.store.append_track_chunk(recording["id"], "mic", 0, b"mic")
        self.store.append_track_chunk(recording["id"], "system", 0, b"sys")
        self.store.append_track_chunk(recording["id"], "mixed", 0, b"mix")
        finalized, _ = self.store.finalize(recording["id"])

        self.assertEqual(finalized["status"], "recorded")
        self.assertEqual(finalized["capture_mode"], "both")
        self.assertEqual({track["id"] for track in finalized["audio_tracks"]}, {"mic", "system", "mixed"})
        self.assertEqual(self.store.track_audio_path(recording["id"], "mic").read_bytes(), b"mic")
        self.assertEqual(self.store.track_audio_path(recording["id"], "system").read_bytes(), b"sys")
        self.assertEqual(self.store.audio_path(recording["id"]).read_bytes(), b"mix")

        tracks = self.store.transcribable_tracks(recording["id"])
        self.assertEqual([track["id"] for track, _ in tracks], ["mic", "system"])

    def test_native_capture_files_update_track_sizes_on_finalize(self) -> None:
        recording = self.store.create(
            title="Native Call",
            mime_type="audio/wav",
            model="test-model",
            language="it",
            capture_mode="both",
            capture_backend="native",
        )
        session_dir = self.store.session_dir(recording["id"])
        (session_dir / "mic.wav.part").write_bytes(b"mic wav")
        (session_dir / "system.wav.part").write_bytes(b"system wav")
        (session_dir / "recording.wav.part").write_bytes(b"mixed wav")

        finalized, _ = self.store.finalize(recording["id"])

        tracks = {track["id"]: track for track in finalized["audio_tracks"]}
        self.assertEqual(tracks["mic"]["bytes_written"], len(b"mic wav"))
        self.assertEqual(tracks["system"]["bytes_written"], len(b"system wav"))
        self.assertEqual(tracks["mixed"]["bytes_written"], len(b"mixed wav"))
        self.assertEqual(finalized["bytes_written"], len(b"mic wav") + len(b"system wav") + len(b"mixed wav"))

    def test_native_capture_finalized_files_are_not_replaced_by_empty_part_placeholders(self) -> None:
        recording = self.store.create(
            title="Native Call",
            mime_type="audio/wav",
            model="test-model",
            language="it",
            capture_mode="both",
            capture_backend="native",
        )
        session_dir = self.store.session_dir(recording["id"])
        (session_dir / "mic.wav").write_bytes(b"mic wav")
        (session_dir / "system.wav").write_bytes(b"system wav")
        (session_dir / "recording.wav").write_bytes(b"mixed wav")

        finalized, _ = self.store.finalize(recording["id"])

        tracks = {track["id"]: track for track in finalized["audio_tracks"]}
        self.assertEqual(self.store.track_audio_path(recording["id"], "mic").read_bytes(), b"mic wav")
        self.assertEqual(self.store.track_audio_path(recording["id"], "system").read_bytes(), b"system wav")
        self.assertEqual(self.store.audio_path(recording["id"]).read_bytes(), b"mixed wav")
        self.assertEqual(tracks["mic"]["bytes_written"], len(b"mic wav"))
        self.assertEqual(tracks["system"]["bytes_written"], len(b"system wav"))
        self.assertEqual(tracks["mixed"]["bytes_written"], len(b"mixed wav"))
    def test_mark_capture_event_handles_none_or_missing_fields(self) -> None:
        recording = self.create_recording()

        # Test 1: timeline is None (which is the default initialized state)
        event1 = {"type": "info", "message": "starting"}
        updated_meta = self.store.mark_capture_event(recording["id"], event1)
        self.assertEqual(updated_meta["timeline"]["events"], [event1])

        # Test 2: timeline has a value, we append more events
        event2 = {"type": "warning", "message": "high memory usage"}
        updated_meta2 = self.store.mark_capture_event(recording["id"], event2)
        self.assertEqual(updated_meta2["timeline"]["events"], [event1, event2])
        self.assertIn("high memory usage", updated_meta2["warnings"])

        # Test 3: error event marks status as error and appends warning
        event3 = {"type": "error", "message": "microphone lost"}
        updated_meta3 = self.store.mark_capture_event(recording["id"], event3)
        self.assertEqual(updated_meta3["capture_status"], "error")
        self.assertIn("microphone lost", updated_meta3["warnings"])



    def test_manual_screenshot_manifest_is_idempotent_and_keeps_missing_assets_visible(self) -> None:
        recording = self.store.create(
            title="Screenshot call",
            mime_type="audio/wav",
            model="test-model",
            language="it",
            capture_mode="both",
            capture_backend="native",
        )
        capture = {
            "timestamp": 1.25,
            "captured_uptime": 101.25,
            "recording_ready_uptime": 100.0,
            "captured_wall_time": 200.0,
            "display_id": 7,
            "display_title": "Screen 1",
            "width": 1920,
            "height": 1080,
            "thumbnail_width": 640,
            "thumbnail_height": 360,
            "overlay_exclusion": "closedroom_windows",
        }
        first = self.store.save_screenshot(
            recording["id"],
            request_id="same-request",
            capture=capture,
            original=b"\xff\xd8\xfforiginal",
            thumbnail=b"\xff\xd8\xffthumb",
        )
        retry = self.store.save_screenshot(
            recording["id"],
            request_id="same-request",
            capture={**capture, "timestamp": 9.0},
            original=b"\xff\xd8\xffdifferent",
            thumbnail=b"\xff\xd8\xffother",
        )

        self.assertEqual(first["screenshot_id"], retry["screenshot_id"])
        self.assertEqual(len(self.store.list_screenshots(recording["id"])), 1)
        self.assertEqual(self.store.get(recording["id"])["screenshot_count"], 1)

        original_path = self.store.screenshot_asset_path(recording["id"], first["screenshot_id"])
        original_path.unlink()
        listed = self.store.list_screenshots(recording["id"])
        self.assertFalse(listed[0]["available"])
        self.assertTrue(listed[0]["thumbnail_available"])


    def test_visual_v2_marks_deleted_screenshot_source_as_stale_without_mutating_history(self) -> None:
        recording = self.store.create(
            title="Visual source validity",
            mime_type="audio/wav",
            model="test-model",
            language="it",
            capture_mode="both",
            capture_backend="native",
        )
        saved = self.store.save_screenshot(
            recording["id"],
            request_id="validity-request",
            capture={
                "timestamp": 4.0,
                "captured_uptime": 104.0,
                "recording_ready_uptime": 100.0,
                "captured_wall_time": 200.0,
                "display_id": 7,
                "display_title": "Screen 1",
                "width": 1920,
                "height": 1080,
                "thumbnail_width": 640,
                "thumbnail_height": 360,
                "overlay_exclusion": "closedroom_windows",
            },
            original=b"\xff\xd8\xfforiginal",
            thumbnail=b"\xff\xd8\xffthumb",
        )
        observation = {
            "observation_id": "visual-manual-shared",
            "sequence": 1_000_000_000,
            "timestamp": 4.0,
            "task": "shared_content",
            "status": "valid",
            "source": {
                "kind": "manual_screenshot",
                "screenshot_id": saved["screenshot_id"],
                "sha256": saved["sha256"],
            },
        }
        document = {
            "schema_version": 2,
            "observations": [observation],
            "speaker_intervals": [],
            "meeting_state_events": [],
            "share_sessions": [],
            "semantic_links": [],
            "routing_summary": {},
            "manual_screenshot_sources": [{
                "screenshot_id": saved["screenshot_id"],
                "timestamp": 4.0,
                "sha256": saved["sha256"],
                "display_id": 7,
                "status": "processed",
            }],
            "model": "qwen",
            "prompt_version": 3,
        }
        self.store.replace_visual_intelligence_artifacts(
            recording["id"],
            [observation],
            {"version": 2, "status": "completed"},
            document=document,
        )

        current = self.store.get_visual_intelligence_v2(recording["id"])
        self.assertEqual(current["source_validity"]["status"], "current")

        self.store.delete_screenshot(recording["id"], saved["screenshot_id"])
        stale = self.store.get_visual_intelligence_v2(recording["id"])

        self.assertEqual(stale["source_validity"]["status"], "stale")
        self.assertEqual(
            stale["source_validity"]["missing_screenshot_ids"],
            [saved["screenshot_id"]],
        )
        self.assertEqual(
            stale["document"]["manual_screenshot_sources"][0]["screenshot_id"],
            saved["screenshot_id"],
        )


    def test_restart_reconciles_screenshot_orphans_without_dropping_manifest_evidence(self) -> None:
        recording = self.store.create(
            title="Screenshot restart",
            mime_type="audio/wav",
            model="test-model",
            language="it",
            capture_mode="both",
            capture_backend="native",
        )
        capture = {
            "timestamp": 3.0,
            "captured_uptime": 103.0,
            "recording_ready_uptime": 100.0,
            "captured_wall_time": 200.0,
            "display_id": 7,
            "display_title": "Screen 1",
            "width": 1920,
            "height": 1080,
            "thumbnail_width": 640,
            "thumbnail_height": 360,
            "overlay_exclusion": "closedroom_windows",
        }
        saved = self.store.save_screenshot(
            recording["id"],
            request_id="restart-request",
            capture=capture,
            original=b"\xff\xd8\xfforiginal",
            thumbnail=b"\xff\xd8\xffthumb",
        )
        session_dir = self.store.session_dir(recording["id"])
        screenshots_dir = session_dir / "screenshots"
        orphan = screenshots_dir / "screenshot-orphan.jpg"
        orphan.write_bytes(b"\xff\xd8\xfforphan")
        interrupted_temp = session_dir / ".screenshot-capture-temp"
        interrupted_temp.mkdir()
        (interrupted_temp / "half-written.jpg").write_bytes(b"partial")

        self.store.screenshot_asset_path(recording["id"], saved["screenshot_id"]).unlink()

        restarted = RecordingStore(self.root, use_settings_dir=False)
        listed = restarted.list_screenshots(recording["id"])

        self.assertFalse(orphan.exists())
        self.assertFalse(interrupted_temp.exists())
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["screenshot_id"], saved["screenshot_id"])
        self.assertFalse(listed[0]["available"])
        self.assertTrue(listed[0]["thumbnail_available"])
        self.assertEqual(restarted.get(recording["id"])["screenshot_count"], 1)

    def test_finalize_recovers_and_finalizes_recoverable_recording(self) -> None:
        recording = self.create_recording()
        self.store.append_chunk(recording["id"], 0, b"audio-data")

        # Simulate server restart marking it recoverable
        restarted = RecordingStore(self.root, use_settings_dir=False)
        self.assertEqual(restarted.get(recording["id"])["status"], "recoverable")

        # finalize() must be able to stop and finalize a recoverable recording
        finalized, _ = restarted.finalize(recording["id"])
        self.assertEqual(finalized["status"], "recorded")
        self.assertIsNone(finalized.get("error"))

        # Subsequent finalize() call is idempotent
        second_call, _ = restarted.finalize(recording["id"])
        self.assertEqual(second_call["status"], "recorded")

    def test_recover_populates_track_bytes_written(self) -> None:
        recording = self.create_recording()
        self.store.append_chunk(recording["id"], 0, b"track-bytes-here")

        restarted = RecordingStore(self.root, use_settings_dir=False)
        self.assertEqual(restarted.get(recording["id"])["status"], "recoverable")

        recovered = restarted.recover(recording["id"])
        self.assertEqual(recovered["status"], "recorded")
        track = recovered["audio_tracks"][0]
        self.assertGreater(track["bytes_written"], 0)
        self.assertEqual(track["chunk_count"], 1)


if __name__ == "__main__":
    unittest.main()

