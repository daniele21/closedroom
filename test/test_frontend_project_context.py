from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "frontend/src/pages/ProjectsPage.tsx"


class ProjectContextTests(unittest.TestCase):
    def test_local_ui_context_survives_project_view_remount(self) -> None:
        page = PROJECTS.read_text(encoding="utf-8")
        for expected in (
            "PROJECT_VIEW_STORAGE_KEY = 'closedroom.projects.view'",
            "function restoreProjectView()",
            "useMemo(restoreProjectView, [])",
            "useState(savedProjectView.name)",
            "useState<TimeRangeState>(savedProjectView.range)",
            "useState<ActionScope>(savedProjectView.actionScope)",
            "sessionStorage.setItem(PROJECT_VIEW_STORAGE_KEY, JSON.stringify({",
        ):
            self.assertIn(expected, page)

    def test_bad_storage_and_stale_selected_project_recover_safely(self) -> None:
        page = PROJECTS.read_text(encoding="utf-8")
        self.assertIn("catch {\n    return fallback;", page)
        self.assertIn("if (loading) return;", page)
        self.assertIn("projects.some((project) => project.name === selectedProjectName)", page)
        self.assertIn("if (loading || demoMode) return;", page)


if __name__ == "__main__":
    unittest.main()
