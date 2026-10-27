from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "frontend" / "src" / "App.tsx"
CSS = ROOT / "frontend" / "src" / "workspace.css"
UX = ROOT / "design" / "ux-contract.json"


class WorkspaceCoherenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = APP.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")
        self.ux = UX.read_text(encoding="utf-8")

    def test_one_shell_owns_primary_navigation_and_new_meeting(self) -> None:
        self.assertIn('className="workspace-shell"', self.app)
        self.assertIn('className="workspace-rail"', self.app)
        self.assertIn('className="workspace-primary-nav"', self.app)
        self.assertIn('data-tour="new-meeting-btn"', self.app)
        self.assertNotIn('className="app-header', self.app)
        self.assertNotIn('className="app-nav', self.app)

    def test_meetings_is_a_durable_destination_and_today_remains_reachable(self) -> None:
        meeting_page = (ROOT / "frontend/src/pages/MeetingsPage.tsx").read_text(encoding="utf-8")
        self.assertIn("case 'meetings':", self.app)
        self.assertIn("id === 'home' ? 'meetings' : item.id", self.app)
        self.assertIn("label: t('nav.meetings')", self.app)
        self.assertIn("<MeetingArchiveExplorer", meeting_page)
        self.assertIn("navigateTo('home')", meeting_page)
        self.assertIn("activePage === 'meetings'", self.app)

    def test_meeting_stays_a_child_of_today_in_navigation(self) -> None:
        self.assertIn("const todayActive = activePage === 'home' || (activePage === 'meeting' && !meetingFromProject)", self.app)
        self.assertIn("aria-current={item.active ? 'page' : undefined}", self.app)
        self.assertNotIn("{ id: 'meeting'", self.app)

    def test_legacy_recording_details_resolve_to_meeting_without_intercepting_auto_start(self) -> None:
        recording_page = (ROOT / "frontend/src/pages/RecordingPage.tsx").read_text(encoding="utf-8")
        self.assertIn("legacyRecordingDetail = page === 'recording'", self.app)
        self.assertIn("legacySavedRecording = pageName === 'recording'", self.app)
        self.assertIn("!detail.startsWith('auto/')", self.app)
        self.assertIn("window.history.replaceState(null, '', `#meeting/${detail}`)", self.app)
        self.assertIn("navigateTo('meeting', recording.id);", recording_page)

    def test_meeting_back_retains_project_origin(self) -> None:
        meeting = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")
        self.assertIn("meetingOriginRef", self.app)
        self.assertIn("meetingFromProject", self.app)
        self.assertIn("onBack={() => navigateTo(meetingOriginRef.current)}", self.app)
        self.assertIn("onBack?: () => void", meeting)
        self.assertIn("const goBack = () =>", meeting)
        self.assertIn("onClick={() => goBack()}", meeting)

    def test_advanced_and_runtime_controls_are_utilities_not_primary_navigation(self) -> None:
        nav_start = self.app.index('const navItems = [')
        nav_end = self.app.index('];', nav_start)
        nav_block = self.app[nav_start:nav_end]
        self.assertIn("id: 'home'", nav_block)
        self.assertIn("id: 'projects'", nav_block)
        self.assertNotIn("id: 'settings'", nav_block)
        self.assertNotIn("id: 'analysis'", nav_block)
        self.assertNotIn("id: 'transcription'", nav_block)
        self.assertIn('workspace-runtime-status', self.app)
        self.assertIn('workspace-settings-trigger', self.app)

    def test_shell_has_explicit_wide_compact_narrow_and_reduced_motion_behavior(self) -> None:
        self.assertIn('grid-template-columns: 236px minmax(0, 1fr)', self.css)
        self.assertIn('@media (max-width: 980px)', self.css)
        self.assertIn('@media (max-width: 640px)', self.css)
        self.assertIn('grid-template-columns: auto auto minmax(0, 1fr) auto', self.css)
        self.assertIn('.workspace-primary-nav {\n    grid-column: 2;', self.css)
        self.assertIn('.workspace-new-meeting {\n    grid-column: 3;', self.css)
        self.assertIn('.workspace-utility-wrap {\n    grid-column: 4;', self.css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', self.css)
        self.assertIn('position: sticky', self.css)
        self.assertIn('workspace-settings-menu', self.css)

    def test_ui_contract_still_keeps_meeting_primary_and_technical_concepts_hidden(self) -> None:
        self.assertIn('"primary_user_object": "meeting"', self.ux)
        self.assertIn('"implementation_concepts_hidden_by_default"', self.ux)
        self.assertIn('"clear_primary_action_hierarchy": true', self.ux)
        self.assertIn('"platform_appropriate": true', self.ux)


if __name__ == "__main__":
    unittest.main()
