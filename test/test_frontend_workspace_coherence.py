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

    def test_meeting_stays_a_child_of_today_in_navigation(self) -> None:
        self.assertIn("activePage === 'home' || activePage === 'meeting'", self.app)
        self.assertIn("aria-current={item.active ? 'page' : undefined}", self.app)
        self.assertNotIn("{ id: 'meeting'", self.app)

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
