from __future__ import annotations

import importlib.util
import platform
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "macos_ui_driver.py"
HELPER = ROOT / "scripts" / "macos_ax_helper.swift"
SMOKE = ROOT / "scripts" / "real_environment_smoke.py"


def load_driver():
    spec = importlib.util.spec_from_file_location("macos_ui_driver_contract", DRIVER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load macos_ui_driver.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MacOSUiDriverContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver_module = load_driver()
        cls.helper_source = HELPER.read_text(encoding="utf-8")
        cls.smoke_source = SMOKE.read_text(encoding="utf-8")

    def test_helper_cache_path_is_stable_for_same_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "helper.swift"
            cache = root / "cache"
            source.write_text("print(\"v1\")\n", encoding="utf-8")

            first = self.driver_module.MacOSUIDriver(source=source, cache_root=cache)
            second = self.driver_module.MacOSUIDriver(source=source, cache_root=cache)

            first_path = first.helper_binary_path()
            second_path = second.helper_binary_path()
            self.assertEqual(first_path, second_path)
            self.assertEqual(first_path.name, "closedroom-ax-helper")
            self.assertIn(platform.machine() or "unknown", first_path.parts)
            self.assertTrue(first_path.is_relative_to(cache))

    def test_helper_cache_path_changes_when_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "helper.swift"
            cache = root / "cache"
            source.write_text("print(\"v1\")\n", encoding="utf-8")
            first = self.driver_module.MacOSUIDriver(source=source, cache_root=cache)
            first_path = first.helper_binary_path()

            source.write_text("print(\"v2\")\n", encoding="utf-8")
            second = self.driver_module.MacOSUIDriver(source=source, cache_root=cache)
            self.assertNotEqual(first_path, second.helper_binary_path())

    def test_helper_prompts_for_accessibility_as_current_process(self) -> None:
        self.assertIn("AXIsProcessTrustedWithOptions", self.helper_source)
        self.assertIn("kAXTrustedCheckOptionPrompt", self.helper_source)
        self.assertNotIn("if !AXIsProcessTrusted()", self.helper_source)

    def test_permission_contract_names_helper_not_terminal(self) -> None:
        driver_source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("accessibility_helper_permission_required", driver_source)
        self.assertNotIn("terminal_accessibility_permission_required", driver_source)
        self.assertIn("allow closedroom-ax-helper", self.smoke_source)
        self.assertNotIn("allow the Terminal app running this command", self.smoke_source)


if __name__ == "__main__":
    unittest.main()
