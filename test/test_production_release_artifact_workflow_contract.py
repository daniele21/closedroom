from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "production-release-artifact.yml"


class ProductionReleaseArtifactWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_is_manual_main_bound_and_read_only(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn('refs/heads/main', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$SOURCE_REVISION" origin/main', self.workflow)
        self.assertNotIn('[[ "$GITHUB_SHA" == "$SOURCE_REVISION" ]]', self.workflow)
        self.assertIn("contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)
        self.assertNotIn("pull_request:", self.workflow)
        self.assertNotIn("push:", self.workflow)

    def test_uses_protected_release_environment_and_expected_authority_secrets(self) -> None:
        self.assertIn("environment: production-release", self.workflow)
        for secret in (
            "CLOSEDROOM_DEVELOPER_ID_P12_BASE64",
            "CLOSEDROOM_DEVELOPER_ID_P12_PASSWORD",
            "CLOSEDROOM_NOTARY_API_KEY_BASE64",
            "CLOSEDROOM_NOTARY_KEY_ID",
            "CLOSEDROOM_NOTARY_ISSUER_ID",
        ):
            self.assertIn(f"secrets.{secret}", self.workflow)

    def test_keeps_signing_and_notary_authority_in_temporary_keychain(self) -> None:
        self.assertIn("security create-keychain", self.workflow)
        self.assertIn("security import", self.workflow)
        self.assertIn("security set-key-partition-list", self.workflow)
        self.assertIn("xcrun notarytool store-credentials", self.workflow)
        self.assertIn('--keychain "$KEYCHAIN_PATH"', self.workflow)
        self.assertIn("CLOSEDROOM_NOTARY_KEYCHAIN=$KEYCHAIN_PATH", self.workflow)
        self.assertIn("security delete-keychain", self.workflow)
        self.assertIn("Remove protected Apple release authority", self.workflow)

    def test_delegates_build_and_notarization_to_canonical_owner_only(self) -> None:
        self.assertIn("python3 scripts/build_production_artifact.py --root .", self.workflow)
        self.assertNotIn("bash build.sh", self.workflow)
        self.assertNotIn("scripts/build_artifact.sh", self.workflow)
        self.assertNotIn("create_dmg.sh", self.workflow)
        self.assertNotIn("notarytool submit", self.workflow)
        self.assertNotIn("stapler staple", self.workflow)

    def test_verifies_exact_release_lineage_before_upload(self) -> None:
        self.assertIn('refs/tags/${TAG}^{commit}', self.workflow)
        self.assertIn('scripts/product_version.py --root . --expect-tag "$TAG"', self.workflow)
        self.assertIn('"developer-id-notarized"', self.workflow)
        self.assertIn('"app_notarization": "accepted"', self.workflow)
        self.assertIn('"dmg_notarization": "accepted"', self.workflow)
        self.assertIn("production checksums do not match manifest", self.workflow)

    def test_upload_contract_matches_grp4_and_never_publishes(self) -> None:
        self.assertIn(
            "name: closedroom-production-release-${{ inputs.source_revision }}",
            self.workflow,
        )
        self.assertIn("production-release-evidence.json", self.workflow)
        self.assertIn("build-manifest.json", self.workflow)
        self.assertIn("BUILD_CHANGELOG.md", self.workflow)
        self.assertIn("SHA256SUMS", self.workflow)
        self.assertIn("retention-days: 7", self.workflow)
        self.assertNotIn("gh release", self.workflow)
        self.assertNotIn("draft-release.yml", self.workflow)


if __name__ == "__main__":
    unittest.main()
