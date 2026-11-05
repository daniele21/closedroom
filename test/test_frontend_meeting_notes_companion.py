from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEETING = ROOT / "frontend/src/pages/MeetingDetailPage.tsx"
BROWSER = ROOT / "scripts/browser_meeting_note_edit_e2e.mjs"


class MeetingNotesTranscriptCompanionTests(unittest.TestCase):
    def test_saved_meeting_shows_canonical_source_beside_ready_notes(self) -> None:
        page = MEETING.read_text(encoding="utf-8")
        self.assertIn('data-meeting-notes-workspace="true"', page)
        self.assertIn('data-meeting-transcript-companion="true"', page)
        self.assertIn("meeting.transcription.segments?.length", page)
        self.assertIn("segments={meeting.transcription.segments}", page)
        self.assertIn("onTimestampClick={handleTimestampClick}", page)
        self.assertIn("onUpdateNote={handleUpdateNote}", page)
        self.assertIn("onDeleteNote={handleDeleteNote}", page)
        self.assertIn("onClick={() => focusTab('transcript')}", page)
        self.assertIn("aria-controls={panelId('transcript')}", page)
        self.assertIn('data-meeting-primary-notes="true"', page)
        self.assertIn("hasCurrentNotes ? (lang === 'it' ? 'Note e azioni'", page)

    def test_browser_journey_covers_saved_notes_and_source_together(self) -> None:
        browser = BROWSER.read_text(encoding="utf-8")
        self.assertIn("Ready Meeting lacks synchronized notes/transcript companion", browser)


if __name__ == "__main__":
    unittest.main()
