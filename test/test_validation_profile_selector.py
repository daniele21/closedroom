from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "select_validation_profile.py"
spec = importlib.util.spec_from_file_location("select_validation_profile", SCRIPT)
assert spec and spec.loader
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


class ValidationProfileSelectorTests(unittest.TestCase):
    def test_docs_only_is_lean(self):
        result = selector.select_profile(["docs/current-state.md", "README.md"])
        self.assertEqual(result["profile"], "lean")

    def test_ordinary_frontend_change_is_scoped(self):
        result = selector.select_profile(["frontend/src/pages/SettingsPage.tsx"])
        self.assertEqual(result["profile"], "scoped")
        self.assertNotIn("browser-e2e", result["required_gates"])

    def test_saved_meeting_ui_change_is_scoped_with_browser_e2e(self):
        result = selector.select_profile(["frontend/src/pages/MeetingDetailPage.tsx"])
        self.assertEqual(result["profile"], "scoped")
        self.assertIn("meeting_ui_integration", result["risk_dimensions"])
        self.assertIn("browser-e2e", result["required_gates"])

    def test_saved_meeting_browser_harnesses_select_their_own_gate(self):
        harnesses = (
            "scripts/browser_archive_search_e2e.mjs",
            "scripts/browser_meeting_note_edit_e2e.mjs",
            "scripts/browser_meeting_preparation_e2e.mjs",
            "scripts/browser_meeting_ui_e2e.mjs",
            "scripts/browser_record_while_ai_busy_e2e.mjs",
            "scripts/browser_saved_meeting_e2e.mjs",
            "scripts/browser_workspace_coherence_e2e.mjs",
        )
        for path in harnesses:
            with self.subTest(path=path):
                result = selector.select_profile([path])
                self.assertEqual(result["profile"], "scoped")
                self.assertIn("meeting_ui_integration", result["risk_dimensions"])
                self.assertIn("browser-e2e", result["required_gates"])

    def test_preparation_backend_change_preserves_depth_and_adds_browser_e2e(self):
        expected_profiles = {
            "src/local_asr_server/meeting_preparation.py": "scoped",
            "src/local_asr_server/services/analysis_service.py": "strong",
            "src/local_asr_server/structured_notes.py": "scoped",
        }
        for path, expected_profile in expected_profiles.items():
            with self.subTest(path=path):
                result = selector.select_profile([path])
                self.assertEqual(result["profile"], expected_profile)
                self.assertIn("meeting_ui_integration", result["risk_dimensions"])
                self.assertIn("browser-e2e", result["required_gates"])

    def test_browser_e2e_is_deferred_during_iteration(self):
        result = selector.select_profile(["frontend/src/pages/MeetingDetailPage.tsx"], stage="iteration")
        self.assertEqual(result["required_gates"], ["governance"])

    def test_runtime_change_is_strong(self):
        result = selector.select_profile(["src/local_asr_server/runtime/service_manager.py"])
        self.assertEqual(result["profile"], "strong")

    def test_e2e_contract_dot_path_is_strong(self):
        result = selector.select_profile([".engineering/e2e.json"])
        self.assertEqual(result["profile"], "strong")

    def test_workflow_dot_path_is_full(self):
        result = selector.select_profile([".github/workflows/preflight.yml"])
        self.assertEqual(result["profile"], "full")

    def test_stage_environment_policy_verifier_is_full(self):
        result = selector.select_profile(["scripts/verify_stage_environment_policy.py"])
        self.assertEqual(result["profile"], "full")

    def test_exact_dotfile_keeps_its_profile(self):
        result = selector.select_profile([".editorconfig"])
        self.assertEqual(result["profile"], "lean")

    def test_dot_slash_prefix_preserves_dot_path_classification(self):
        self.assertEqual(
            selector.classify_path("./.engineering/e2e.json"),
            selector.classify_path(".engineering/e2e.json"),
        )

    def test_build_or_selector_change_is_full(self):
        for path in ("build.sh", "pyproject.toml", "scripts/select_validation_profile.py"):
            with self.subTest(path=path):
                self.assertEqual(selector.select_profile([path])["profile"], "full")

    def test_strongest_changed_path_wins(self):
        result = selector.select_profile(
            ["docs/current-state.md", "frontend/src/App.tsx", "src/local_asr_server/catalog.py"]
        )
        self.assertEqual(result["profile"], "strong")

    def test_unknown_path_fails_safe_full(self):
        result = selector.select_profile(["unexpected/tooling.conf"])
        self.assertEqual(result["profile"], "full")
        self.assertIn("fails safe", result["reason"])


if __name__ == "__main__":
    unittest.main()