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
        progress = (ROOT / "frontend/src/components/meeting/MeetingProcessingStatus.tsx").read_text(encoding="utf-8")
        self.assertIn("<MeetingProcessingStatus", meeting)
        self.assertIn('data-meeting-job-progress={job.type}', progress)
        self.assertIn("isASRTrackProgress", progress)
        self.assertIn("processed_audio_seconds > 0", progress)
        self.assertIn("aria-valuenow={percent ?? undefined}", progress)
        self.assertIn("meeting-progress-indeterminate", progress)
        self.assertIn('role="status"', progress)

    def test_archive_and_permanent_delete_are_distinct_explicit_actions(self) -> None:
        detail = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
        library = (ROOT / "frontend/src/components/workspace/MeetingSearchDialog.tsx").read_text(encoding="utf-8")
        search_api = (ROOT / "frontend/src/api/meetingSearchApi.ts").read_text(encoding="utf-8")
        client = (ROOT / "frontend/src/api/apiClient.ts").read_text(encoding="utf-8")
        self.assertIn("ApiClient.archiveMeeting(meeting.id)", detail)
        self.assertIn("ApiClient.restoreMeeting(meeting.id)", detail)
        self.assertIn("ApiClient.deleteMeeting(meeting.id)", detail)
        self.assertIn('dataTour="meeting-delete-confirm"', detail)
        self.assertIn('data-meeting-delete-confirm-action="true"', detail)
        self.assertNotIn("window.confirm", detail)
        self.assertIn("meeting.recording.archived_at &&", detail)
        self.assertIn('data-archived-meetings="true"', library)
        self.assertIn("setShowArchived(true)", library)
        self.assertIn("searchMeetingArchive(query, 1, PAGE_SIZE, controller.signal, showArchived)", library)
        self.assertIn("if (archived) params.set('archived', 'true')", search_api)
        self.assertIn("async archiveMeeting(recordingId: string)", client)
        self.assertIn("async restoreMeeting(recordingId: string)", client)
        self.assertIn("async deleteMeeting(recordingId: string)", client)


if __name__ == "__main__":
    unittest.main()
