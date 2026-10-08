from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MeetingLifecycleFrontendContracts(unittest.TestCase):
    def test_native_overlay_can_accept_keyboard_for_note_input(self) -> None:
        native = (ROOT / "src/local_asr_server/window.py").read_text(encoding="utf-8")
        overlay = (ROOT / "frontend/src/pages/RecordingOverlayPage.tsx").read_text(encoding="utf-8")
        self.assertIn("class InteractiveOverlayPanel(NSPanel):", native)
        self.assertIn("def canBecomeKeyWindow(self) -> bool:", native)
        self.assertIn("self.overlay_window = InteractiveOverlayPanel.alloc()", native)
        self.assertIn('data-note-close="true"', overlay)
        self.assertIn('data-note-save="true"', overlay)
        self.assertIn("closeNoteComposer()", overlay)
        self.assertIn("noteInputRef.current?.focus()", overlay)
        self.assertIn('className="w-full select-text resize-none', overlay)

    def test_meeting_progress_displays_running_and_measured_state(self) -> None:
        meeting = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
        self.assertIn('data-meeting-job-progress={job.type}', meeting)
        self.assertIn("max={100}", meeting)
        self.assertIn("value={Math.min(job.progress, 100)}", meeting)
        self.assertIn("animate-pulse", meeting)
        self.assertIn('role="status"', meeting)

    def test_archive_and_permanent_delete_are_distinct_explicit_actions(self) -> None:
        detail = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
        drawer = (ROOT / "frontend/src/components/workspace/MeetingListDialog.tsx").read_text(encoding="utf-8")
        client = (ROOT / "frontend/src/api/apiClient.ts").read_text(encoding="utf-8")
        self.assertIn("ApiClient.archiveMeeting(meeting.id)", detail)
        self.assertIn("ApiClient.restoreMeeting(meeting.id)", detail)
        self.assertIn("ApiClient.deleteMeeting(meeting.id)", detail)
        self.assertIn('dataTour="meeting-delete-confirm"', detail)
        self.assertIn('data-meeting-delete-confirm-action="true"', detail)
        self.assertNotIn("window.confirm", detail)
        self.assertIn("meeting.recording.archived_at &&", detail)
        self.assertIn('data-archived-meetings="true"', drawer)
        self.assertIn("listArchivedMeetings", client)


if __name__ == "__main__":
    unittest.main()
