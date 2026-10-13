from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github/workflows"

class NoRemoteAppBuildContractTests(unittest.TestCase):
    def test_no_github_actions_app_or_production_build(self):
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(workflow=path.name):
                self.assertNotIn("bash scripts/build_artifact.sh", text)
                self.assertNotIn("python3 scripts/build_production_artifact.py", text)
                self.assertNotIn("Build unique finalized artifact", text)
                self.assertNotIn("Upload build + smoke evidence", text)

    def test_no_full_media_or_package_artifact_uploads_in_actions(self):
        preflight = (WORKFLOWS / "preflight.yml").read_text(encoding="utf-8")
        self.assertNotIn("uses: actions/upload-artifact@v4\n        with:\n          name: closedroom-browser-meeting-", preflight)
        self.assertNotIn("path: dist/evidence/browser-meeting-ui/**", preflight)
        self.assertNotIn("  packaged-app:\n", preflight)
        self.assertIn("pending_external_gates", preflight)
        self.assertIn("ci_validated_gates", preflight)
        self.assertIn("source-tests", preflight)

    def test_package_gate_is_still_required_outside_actions(self):
        selector = (ROOT / "scripts/select_validation_profile.py").read_text(encoding="utf-8")
        self.assertIn('gates.append("packaged-app")', selector)
        self.assertIn('"release-critical"', selector)
        cmd = (ROOT / ".engineering/commands.json").read_text(encoding="utf-8")
        self.assertIn("scripts/build_production_artifact.py", cmd)
        self.assertIn("scripts/publish_local_draft_release.sh", cmd)

if __name__ == "__main__":
    unittest.main()
