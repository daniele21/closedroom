from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "record_while_ai_busy_target_mac.py"


def load_contention():
    scripts = str(ROOT / "scripts")
    sys.path.insert(0, scripts)
    try:
        spec = importlib.util.spec_from_file_location(
            "record_while_ai_busy_target_mac", SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(scripts)


class RecordWhileAiBusyReleaseToolingTests(unittest.TestCase):
    def test_script_is_valid_python_and_declares_target_journey(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('"journey_id": "record-while-ai-busy"', source)
        self.assertIn('"ui_evidence_mode": "full_media"', source)
        self.assertIn('"truthful_waiting_state_observed"', source)
        self.assertIn('"managed_ai_still_active_while_waiting"', source)
        self.assertIn('"capture_not_active_while_ai_busy"', source)
        self.assertIn('"capture_started_after_safe_boundary"', source)
        self.assertIn('"managed_ai_is_local_mlx"', source)
        self.assertIn('"contention_native_both_tracks"', source)
        self.assertIn('"contention_full_media_complete"', source)
        self.assertIn("01-ai-busy-waiting.png", source)
        self.assertIn("02-recording-after-boundary.png", source)
        self.assertIn("contention-journey.mov", source)
        self.assertIn("measured.existing_directory", source)

    def test_native_both_requires_mic_and_system_tracks(self) -> None:
        module = load_contention()
        complete = {
            "capture_backend": "native",
            "capture_mode": "both",
            "nonempty_track_sources": ["mic", "system"],
        }
        self.assertTrue(module.native_both_with_tracks(complete))
        self.assertFalse(
            module.native_both_with_tracks(
                {**complete, "nonempty_track_sources": ["mic"]}
            )
        )
        self.assertFalse(
            module.native_both_with_tracks(
                {**complete, "capture_backend": "browser"}
            )
        )

    def test_missing_sandbox_paths_never_resolve_to_working_directory(self) -> None:
        module = load_contention()
        self.assertIsNone(module.measured.existing_directory(None))
        self.assertIsNone(module.measured.existing_directory(""))
        self.assertIsNone(
            module.measured.existing_directory(
                "/definitely/missing/closedroom-release-sandbox"
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                module.measured.existing_directory(tmp),
                Path(tmp).resolve(),
            )

    def test_canonical_release_evidence_runs_measured_and_contention(self) -> None:
        commands = json.loads(
            (ROOT / ".engineering" / "commands.json").read_text(encoding="utf-8")
        )
        release = commands["commands"]["release_evidence"]["run"]
        self.assertIn("measured_release_target_mac.py", release)
        self.assertIn("record_while_ai_busy_target_mac.py", release)
        self.assertIn("&&", release)


if __name__ == "__main__":
    unittest.main()
