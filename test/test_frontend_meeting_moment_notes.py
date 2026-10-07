from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "frontend" / "src" / "pages" / "RecordingOverlayPage.tsx"
TRANSCRIPT = ROOT / "frontend" / "src" / "components" / "transcription" / "TranscriptTextView.tsx"
MEETING = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
ACCESSORIES = ROOT / "frontend" / "src" / "hooks" / "useMeetingAccessories.ts"
CLIENT = ROOT / "frontend" / "src" / "api" / "apiClient.ts"
STRUCTURED_UI = ROOT / "frontend" / "src" / "components" / "meeting" / "StructuredNotesEditor.tsx"
MENUBAR = ROOT / "src" / "local_asr_server" / "menubar.py"
STRUCTURED = ROOT / "src" / "local_asr_server" / "structured_notes.py"


class FrontendMeetingMomentNotesContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay = OVERLAY.read_text(encoding="utf-8")
        cls.transcript = TRANSCRIPT.read_text(encoding="utf-8")
        cls.meeting = MEETING.read_text(encoding="utf-8")
        cls.accessories = ACCESSORIES.read_text(encoding="utf-8")
        cls.client = CLIENT.read_text(encoding="utf-8")
        cls.structured_ui = STRUCTURED_UI.read_text(encoding="utf-8")
        cls.menubar = MENUBAR.read_text(encoding="utf-8")
        cls.structured = STRUCTURED.read_text(encoding="utf-8")

    def test_overlay_anchors_note_before_text_commit_and_keeps_minimal_composer(self) -> None:
        self.assertIn("ApiClient.recordingNoteAnchor(recordingId)", self.overlay)
        self.assertIn("ApiClient.createRecordingNote(recordingId", self.overlay)
        self.assertLess(
            self.overlay.index("ApiClient.recordingNoteAnchor(recordingId)"),
            self.overlay.index("ApiClient.createRecordingNote(recordingId"),
        )
        self.assertIn('data-note-composer="true"', self.overlay)
        self.assertIn('data-note-action="true"', self.overlay)
        self.assertIn('data-note-undo="true"', self.overlay)
        self.assertIn("event.key === 'Enter' && !event.shiftKey", self.overlay)
        self.assertIn("event.key === 'Escape'", self.overlay)
        self.assertIn("maxLength={4000}", self.overlay)
        self.assertNotIn("contentEditable", self.overlay)

    def test_meeting_projects_notes_by_timestamp_without_mutating_asr_segments(self) -> None:
        self.assertIn("segment.start <= note.timestamp && note.timestamp <= segment.end", self.transcript)
        self.assertIn("notePlacement.anchored.get(seg.id)", self.transcript)
        self.assertIn("data-user-note-id={note.note_id}", self.transcript)
        self.assertIn("onTimestampClick?.(note.timestamp)", self.transcript)
        self.assertIn("ApiClient.updateRecordingNote", self.meeting)
        self.assertIn("ApiClient.deleteRecordingNote", self.meeting)
        self.assertIn("notes={notes}", self.meeting)
        self.assertIn("ApiClient.recordingNotes(recordingId)", self.accessories)
        self.assertNotIn("seg.text =", self.transcript)
        self.assertNotIn("seg.id =", self.transcript)

    def test_note_api_is_source_specific_and_shared_by_overlay_meeting_and_menubar(self) -> None:
        for endpoint in (
            "/notes/anchor",
            "/notes",
        ):
            self.assertIn(endpoint, self.client)
        self.assertIn('"source_kind": "user_note"', (ROOT / "src" / "local_asr_server" / "recordings.py").read_text(encoding="utf-8"))
        self.assertIn("/notes/anchor", self.menubar)
        self.assertIn("/notes", self.menubar)

    def test_structured_notes_keep_user_note_provenance_distinct(self) -> None:
        self.assertIn('"source_type": "user_note"', self.structured)
        self.assertIn('"evidence_basis": "user_authored"', self.structured)
        self.assertIn("source_type === 'user_note'", self.structured_ui)
        self.assertIn("basis === 'user_note'", self.structured_ui)
        self.assertIn("Never say something was discussed, said, agreed, decided or requested", self.structured)

    def test_menubar_is_meeting_aware_and_hides_healthy_server_chrome(self) -> None:
        self.assertIn("＋ Nuovo meeting", self.menubar)
        self.assertIn("✎ Aggiungi nota", self.menubar)
        self.assertIn("▣ Screenshot", self.menubar)
        self.assertIn("Apri controlli registrazione", self.menubar)
        self.assertIn('self._update_status_item("Pronto")', self.menubar)
        self.assertIn('self._update_status_item(f"● {title}")', self.menubar)
        self.assertIn('rumps.MenuItem("Recenti")', self.menubar)
        self.assertIn("CarbonHotKeyManager", self.menubar)
        self.assertIn('"<cmd>+<shift>+t"', self.menubar)
        self.assertIn('"<cmd>+<shift>+v"', self.menubar)
        self.assertNotIn('"<cmd>+<shift>+r": self._shortcut_toggle_recording', self.menubar)
        self.assertNotIn("Server attivo ✅", self.menubar)


if __name__ == "__main__":
    unittest.main()
