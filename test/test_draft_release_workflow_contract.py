from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "draft-release.yml"


class DraftReleaseWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_is_manual_and_uses_minimal_required_permissions(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("actions: read", self.workflow)
        self.assertIn("contents: write", self.workflow)
        self.assertNotIn("pull_request:", self.workflow)
        self.assertNotIn("push:", self.workflow)

    def test_requires_existing_tag_on_exact_main_history(self) -> None:
        self.assertIn('refs/heads/main', self.workflow)
        self.assertIn('refs/tags/${TAG}^{commit}', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$SOURCE_REVISION" origin/main', self.workflow)
        self.assertNotIn('main_commit="$(git rev-parse origin/main)"', self.workflow)
        self.assertIn('scripts/product_version.py --root . --expect-tag "$TAG"', self.workflow)
        self.assertIn('docs/releases/${TAG}.md', self.workflow)

    def test_consumes_only_canonical_successful_same_source_artifact(self) -> None:
        self.assertIn('actions/runs/${ARTIFACT_RUN_ID}', self.workflow)
        self.assertIn('.github/workflows/production-release-artifact.yml', self.workflow)
        self.assertIn('closedroom-production-release-${SOURCE_REVISION}', self.workflow)
        self.assertIn('"workflow_dispatch"', self.workflow)
        self.assertIn('"main"', self.workflow)
        self.assertIn(".conclusion", self.workflow)
        self.assertIn(".head_sha", self.workflow)
        self.assertIn('gh run download "$ARTIFACT_RUN_ID"', self.workflow)
        self.assertNotIn("inputs.artifact_name", self.workflow)
        self.assertIn("exactly one build-manifest.json", self.workflow)

    def test_delegates_release_validation_to_grp3_adapter(self) -> None:
        self.assertIn("scripts/prepare_github_release.py", self.workflow)
        self.assertIn("release-staging/release-plan.json", self.workflow)
        self.assertIn("release-staging/RELEASE_NOTES.md", self.workflow)
        self.assertIn(".draft == true", self.workflow)
        self.assertIn("(.assets | length) == 4", self.workflow)

    def test_draft_is_fail_closed_and_never_builds_or_publishes(self) -> None:
        self.assertIn("--draft", self.workflow)
        self.assertIn("--verify-tag", self.workflow)
        self.assertIn("refusing to modify a published release", self.workflow)
        self.assertIn('gh release upload "$TAG"', self.workflow)
        self.assertIn("--clobber", self.workflow)
        self.assertIn("release is not draft", self.workflow)
        self.assertIn("release body mismatch", self.workflow)
        self.assertNotIn("--draft=false", self.workflow)
        self.assertNotIn("build_production_artifact.py", self.workflow)
        self.assertNotIn("build_artifact.sh", self.workflow)
        self.assertNotIn("bash build.sh", self.workflow)

    def test_uploaded_inventory_is_verified_by_name_size_and_digest(self) -> None:
        self.assertIn("/tmp/expected-assets.tsv", self.workflow)
        self.assertIn("/tmp/actual-assets.tsv", self.workflow)
        self.assertIn('("sha256:" + .sha256)', self.workflow)
        self.assertIn("(.digest // \"\")", self.workflow)
        self.assertIn("X-GitHub-Api-Version: 2026-03-10", self.workflow)
        self.assertIn("diff -u /tmp/expected-assets.tsv /tmp/actual-assets.tsv", self.workflow)
        self.assertIn("unexpected assets", self.workflow)


if __name__ == "__main__":
    unittest.main()
