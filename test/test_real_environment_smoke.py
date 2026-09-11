from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "real_environment_smoke.py"
SCRIPTS_DIR = SCRIPT.parent


def load_module():
    spec = importlib.util.spec_from_file_location("real_environment_smoke", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load real_environment_smoke.py")
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


class RealEnvironmentSmokeHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = load_module()

    def test_newest_only_returns_a_run_owned_recording(self) -> None:
        before = {"old-a", "old-b"}
        recordings = [
            {"id": "old-a", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "new-1", "created_at": "2026-01-02T00:00:00Z"},
            {"id": "new-2", "created_at": "2026-01-03T00:00:00Z"},
        ]
        self.assertEqual(self.smoke.newest(before, recordings)["id"], "new-2")
        self.assertIsNone(self.smoke.newest(before, recordings[:1]))

    def test_source_tracks_require_persisted_bytes_and_chunks(self) -> None:
        recording = {
            "audio_tracks": [
                {"source": "mic", "bytes_written": 40, "chunk_count": 1},
                {"source": "system", "bytes_written": 80, "chunk_count": 2},
                {"source": "mixed", "bytes_written": 0, "chunk_count": 0},
            ]
        }
        self.assertEqual(self.smoke.source_tracks_with_data(recording), {"mic", "system"})

    def test_evidence_is_separate_from_immutable_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = self.smoke.evidence_path(root, None)
            self.assertTrue(str(destination).startswith(str(root / "dist" / "evidence" / "real-environment")))
            self.assertNotIn("dist/artifacts", str(destination))

    def test_permission_remediation_is_specific_and_rerunnable(self) -> None:
        steps = self.smoke.permissions_help(
            {"microphone": "denied", "screen_capture": "required"},
            accessibility=True,
        )
        text = " ".join(steps)
        self.assertIn("Accessibility", text)
        self.assertIn("Microphone", text)
        self.assertIn("Screen & System Audio Recording", text)
        self.assertIn("Re-run", text)

    def test_git_state_reports_dirty_entries_without_hiding_paths(self) -> None:
        responses = iter(["30c3147b891b", " M scripts/local.py\n?? scratch.txt\n"])
        with mock.patch.object(self.smoke, "run", side_effect=lambda *_args, **_kwargs: next(responses)):
            revision, entries = self.smoke.git_state(Path("/tmp/repo"))
        self.assertEqual(revision, "30c3147b891b")
        self.assertEqual(entries, [" M scripts/local.py", "?? scratch.txt"])

    def test_manifest_revision_uses_canonical_nested_source(self) -> None:
        manifest = {
            "source": {"revision": "9940e83912b2", "dirty": False},
            "source_revision": "stale-top-level",
        }
        self.assertEqual(self.smoke.manifest_source_revision(manifest), "9940e83912b2")

    def test_revision_matching_never_accepts_missing_identity(self) -> None:
        self.assertTrue(self.smoke.revisions_match("9940e83912b2", "9940e83912b256cd"))
        self.assertFalse(self.smoke.revisions_match("9940e83912b2", ""))
        self.assertFalse(self.smoke.revisions_match("", "9940e83912b2"))
        self.assertFalse(self.smoke.revisions_match("9940e83912b2", "7b95d718a35e"))

    def test_search_focus_accepts_text_and_search_fields_only(self) -> None:
        self.assertTrue(self.smoke.search_focus_exposed("AXTextField | Search meeting"))
        self.assertTrue(self.smoke.search_focus_exposed("AXSearchField | Search meeting"))
        self.assertFalse(self.smoke.search_focus_exposed("AXButton | Search meeting"))
        self.assertFalse(self.smoke.search_focus_exposed("unknown"))

    def test_wait_still_rejects_terminal_ui_automation_errors(self) -> None:
        with self.assertRaises(self.smoke.UIAutomationError):
            self.smoke.wait(
                lambda: (_ for _ in ()).throw(self.smoke.UIAutomationError("ax_press_failed")),
                timeout=0.1,
                interval=0.01,
            )


if __name__ == "__main__":
    unittest.main()
