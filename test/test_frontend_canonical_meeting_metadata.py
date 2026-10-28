"""Canonical saved Meeting owns editable title/project, reusing recording persistence."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEETING = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
LEGACY = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
PROJECTS = (ROOT / "frontend/src/pages/ProjectsPage.tsx").read_text(encoding="utf-8")


class CanonicalMeetingMetadataTests(unittest.TestCase):
    def test_title_edit_uses_existing_recording_owner(self) -> None:
        self.assertIn('data-meeting-rename="true"', MEETING)
        self.assertIn('data-meeting-title-input="true"', MEETING)
        self.assertIn("ApiClient.updateRecording(id, { title })", MEETING)
        self.assertIn("editedTitle.trim()", MEETING)
        self.assertIn("t('transcription.titleEmptyError')", MEETING)

    def test_project_edit_uses_same_owner_as_projects(self) -> None:
        self.assertIn('data-meeting-project-edit="true"', MEETING)
        self.assertIn("<ProjectPromptModal", MEETING)
        self.assertIn("ApiClient.listProjects()", MEETING)
        self.assertIn("ApiClient.updateRecording(id, { project_name: projectName })", MEETING)
        self.assertIn("ApiClient.updateRecording(activeRecordingForProject.id, { project_name: projectName })", PROJECTS)

    def test_results_bound_to_original_meeting_and_demo_read_only(self) -> None:
        self.assertIn("currentRecordingIdRef.current !== id", MEETING)
        self.assertIn("current?.id === id", MEETING)
        self.assertIn("if (!meeting || !recordingId || demoMode || isBusy) return", MEETING)
        self.assertIn("if (currentRecordingIdRef.current === id)", MEETING)

    def test_legacy_bookmarks_remain_canonical(self) -> None:
        self.assertIn("const legacySavedRecording", LEGACY)
        self.assertIn("window.history.replaceState(null, '', `#meeting/${detail}`)", LEGACY)
        self.assertIn("detail.startsWith('auto/')", LEGACY)


if __name__ == "__main__":
    unittest.main()
