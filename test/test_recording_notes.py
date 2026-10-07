from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_asr_server.recordings import RecordingConflict, RecordingNotFound, RecordingStore


class RecordingNotesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = RecordingStore(self.root, use_settings_dir=False)
        self.recording = self.store.create(
            title="Notes fixture",
            mime_type="audio/wav",
            model="test-model",
            language="it",
            capture_mode="both",
            capture_backend="native",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_note_create_is_idempotent_and_uses_timestamp_as_stable_anchor(self) -> None:
        first = self.store.create_note(
            self.recording["id"],
            request_id="note-request-1",
            timestamp=42.25,
            text="  Ask Marco for updated numbers.  ",
        )
        retry = self.store.create_note(
            self.recording["id"],
            request_id="note-request-1",
            timestamp=99.0,
            text="A duplicate request must not replace the original.",
        )

        self.assertEqual(first["note_id"], retry["note_id"])
        self.assertEqual(first["timestamp"], 42.25)
        self.assertEqual(retry["timestamp"], 42.25)
        self.assertEqual(first["text"], "Ask Marco for updated numbers.")
        self.assertEqual(first["source_kind"], "user_note")
        self.assertEqual(first["revision"], 1)
        self.assertEqual(self.store.get(self.recording["id"])["note_count"], 1)
        self.assertEqual(len(self.store.list_notes(self.recording["id"])), 1)

    def test_note_edit_requires_revision_and_never_changes_anchor(self) -> None:
        created = self.store.create_note(
            self.recording["id"],
            request_id="note-request-edit",
            timestamp=18.5,
            text="Initial thought",
        )
        updated = self.store.update_note(
            self.recording["id"],
            created["note_id"],
            text="Updated after the meeting",
            revision=created["revision"],
        )

        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["timestamp"], 18.5)
        self.assertEqual(updated["text"], "Updated after the meeting")
        with self.assertRaises(RecordingConflict):
            self.store.update_note(
                self.recording["id"],
                created["note_id"],
                text="Stale overwrite",
                revision=1,
            )

    def test_notes_survive_store_restart_and_delete_is_durable(self) -> None:
        created = self.store.create_note(
            self.recording["id"],
            request_id="note-request-restart",
            timestamp=3.0,
            text="Persist me",
        )

        restarted = RecordingStore(self.root, use_settings_dir=False)
        listed = restarted.list_notes(self.recording["id"])
        self.assertEqual([item["note_id"] for item in listed], [created["note_id"]])
        self.assertEqual(listed[0]["text"], "Persist me")

        restarted.delete_note(self.recording["id"], created["note_id"])
        restarted_again = RecordingStore(self.root, use_settings_dir=False)
        self.assertEqual(restarted_again.list_notes(self.recording["id"]), [])
        self.assertEqual(restarted_again.get(self.recording["id"])["note_count"], 0)
        with self.assertRaises(RecordingNotFound):
            restarted_again.delete_note(self.recording["id"], created["note_id"])

    def test_empty_or_invalid_notes_are_rejected(self) -> None:
        with self.assertRaises(RecordingConflict):
            self.store.create_note(
                self.recording["id"],
                request_id="empty-note",
                timestamp=1.0,
                text="   ",
            )
        with self.assertRaises(RecordingConflict):
            self.store.create_note(
                self.recording["id"],
                request_id="bad-time",
                timestamp=float("nan"),
                text="Nope",
            )


if __name__ == "__main__":
    unittest.main()
