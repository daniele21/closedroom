from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "diagnose_keyboard_shortcut_target_mac.py"


def load_script():
    spec = importlib.util.spec_from_file_location("keyboard_shortcut_diagnostic", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load keyboard diagnostic script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KeyboardShortcutDiagnosticContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script()
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_classification_distinguishes_shortcut_from_search_ui(self) -> None:
        self.assertEqual(
            self.module.classify(True, None),
            "shortcut_delivery_succeeded",
        )
        self.assertEqual(
            self.module.classify(False, True),
            "shortcut_delivery_failed_search_ui_healthy",
        )
        self.assertEqual(
            self.module.classify(False, False),
            "search_ui_or_ax_activation_failed",
        )

    def test_persisted_focus_is_role_only(self) -> None:
        self.assertIn('raw.split("|", 1)[0].strip()', self.source)
        self.assertNotIn('"focused": DRIVER.focused', self.source)
        self.assertIn(
            "UI labels, titles, input values, transcript text and meeting text are not persisted",
            self.source,
        )

    def test_diagnostic_reuses_exact_artifact_without_release_qualification(self) -> None:
        self.assertIn('"qualification_scope": "diagnostic_only"', self.source)
        self.assertIn("artifact_revision_mismatch", self.source)
        self.assertIn('report["status"] = "complete"', self.source)

    def test_diagnostic_navigates_home_before_search_probe(self) -> None:
        nav = 'DRIVER.press(pid, LABELS["home"])'
        search = 'home_search_available = wait(lambda: DRIVER.exists(pid, LABELS["search"])'
        self.assertIn('home_navigation_available = wait(lambda: DRIVER.exists(pid, LABELS["home"])', self.source)
        self.assertIn(nav, self.source)
        self.assertIn(search, self.source)
        self.assertLess(self.source.index(nav), self.source.index(search))
        self.assertIn("home_search_control_missing_after_navigation", self.source)


if __name__ == "__main__":
    unittest.main()
