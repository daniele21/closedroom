from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "publish_local_draft_release.sh"

class LocalDraftReleaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")

    def test_source_identity_and_tag_are_checked(self):
        for required in (
            "git rev-parse HEAD", "git status --porcelain", "git fetch origin main --tags",
            'refs/tags/${tag}^{commit}', "git merge-base --is-ancestor",
            "scripts/product_version.py", "docs/releases/", "source-revision",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.script)

    def test_prepares_immutable_qualified_artifact_as_draft_only(self):
        for required in (
            "scripts/prepare_github_release.py", "release-plan.json", ".assets | length) == 4",
            "--draft", "--verify-tag", "Release already exists", "GITHUB_ACTIONS",
            "gh", "release create",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.script)
        self.assertNotIn("build_production_artifact.py", self.script)
        self.assertNotIn("build_artifact.sh", self.script)

    def test_retired_remote_release_workflows_are_absent(self):
        self.assertFalse((ROOT / ".github/workflows/draft-release.yml").exists())
        self.assertFalse((ROOT / ".github/workflows/production-release-artifact.yml").exists())

if __name__ == "__main__":
    unittest.main()
