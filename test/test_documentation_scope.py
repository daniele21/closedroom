from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentationScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = json.loads((ROOT / ".engineering/documentation-policy.json").read_text())
        self.write_policy()

    def write_policy(self) -> None:
        target = self.root / ".engineering/documentation-policy.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(self.policy))

    def oversized_guide(self, relative: str) -> None:
        path = self.root / relative / "AGENTS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("instruction\n" * 151)

    def verify(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/verify_docs.py"), "--root", str(self.root)],
            capture_output=True, text=True, check=False,
        )

    def test_generated_and_dependency_guides_do_not_fail_project_budget(self) -> None:
        for directory in (".cache/uv/vendor", "build_venv/lib/vendor", ".venv/lib/vendor",
                          "frontend/node_modules/vendor", "dist/artifacts", "build/lib"):
            self.oversized_guide(directory)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_project_guide_still_fails_budget(self) -> None:
        self.oversized_guide("src/new_owner")
        result = self.verify()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("scoped AGENTS too long", result.stdout)
        self.assertIn("src/new_owner/AGENTS.md", result.stdout)

    def test_policy_path_exclusion_does_not_hide_same_named_source_directory(self) -> None:
        self.policy["context_exclude_directories"] = ["generated/dependencies"]
        self.write_policy()
        self.oversized_guide("generated/dependencies/vendor")
        self.assertEqual(self.verify().returncode, 0)
        self.oversized_guide("src/dependencies")
        result = self.verify()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("src/dependencies/AGENTS.md", result.stdout)


if __name__ == "__main__":
    unittest.main()
