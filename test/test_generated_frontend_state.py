from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "scripts" / "generated_frontend_state.py"


def load_module():
    spec = importlib.util.spec_from_file_location("generated_frontend_state_for_test", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


state = load_module()


def run_git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


class GeneratedFrontendStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        run_git(self.root, "init", "-q")
        run_git(self.root, "config", "user.name", "ClosedRoom Test")
        run_git(self.root, "config", "user.email", "test@example.invalid")
        self.static = self.root / state.GENERATED_FRONTEND
        (self.static / "assets").mkdir(parents=True)
        (self.static / "index.html").write_text("original html", encoding="utf-8")
        (self.static / "assets" / "old.js").write_text("original js", encoding="utf-8")
        run_git(self.root, "add", ".")
        run_git(self.root, "commit", "-qm", "base")
        self.head = run_git(self.root, "rev-parse", "HEAD")

    def test_restores_only_generated_output_and_keeps_other_changes(self) -> None:
        state.check_clean(self.root, self.head)
        (self.static / "index.html").write_text("generated html", encoding="utf-8")
        (self.static / "assets" / "old.js").unlink()
        (self.static / "assets" / "new.js").write_text("generated js", encoding="utf-8")
        other = self.root / "keep.txt"
        other.write_text("preserve user work", encoding="utf-8")

        state.restore(self.root, self.head)

        self.assertEqual((self.static / "index.html").read_text(), "original html")
        self.assertEqual((self.static / "assets" / "old.js").read_text(), "original js")
        self.assertFalse((self.static / "assets" / "new.js").exists())
        self.assertEqual(other.read_text(), "preserve user work")
        self.assertEqual(
            run_git(self.root, "status", "--porcelain", "--", state.GENERATED_FRONTEND),
            "",
        )

    def test_dirty_generated_output_is_rejected_before_build(self) -> None:
        preexisting = self.static / "assets" / "important-untracked.js"
        preexisting.write_text("do not remove", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "preexisting changes"):
            state.check_clean(self.root, self.head)
        self.assertEqual(preexisting.read_text(), "do not remove")
        self.assertEqual((self.static / "index.html").read_text(), "original html")

    def test_tracked_edits_are_rejected(self) -> None:
        (self.static / "index.html").write_text("user edit", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "preexisting changes"):
            state.check_clean(self.root, self.head)

    def test_head_change_refuses_destructive_cleanup(self) -> None:
        (self.static / "index.html").write_text("keep after head change", encoding="utf-8")
        run_git(self.root, "add", ".")
        run_git(self.root, "commit", "-qm", "moved")
        with self.assertRaisesRegex(RuntimeError, "HEAD changed"):
            state.restore(self.root, self.head)
        self.assertEqual((self.static / "index.html").read_text(), "keep after head change")

    def test_build_entrypoint_guards_before_vite_and_traps_exit(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")
        preflight = build.index('generated_frontend_state.py" check')
        build_frontend = build.index('CI=true pnpm install --frozen-lockfile')
        self.assertLess(preflight, build_frontend)
        self.assertIn('generated_frontend_state.py" restore', build)
        self.assertIn("trap restore_generated_frontend_on_exit EXIT", build)
        self.assertIn('if [[ "$build_status" -eq 0 ]]; then build_status=1; fi', build)
        self.assertIn('exit "$build_status"', build)


if __name__ == "__main__":
    unittest.main()
