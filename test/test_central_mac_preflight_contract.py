from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
PREFLIGHT = ROOT / ".github/workflows/preflight.yml"
LOCAL_TEST = ROOT / ".github/ci/local-test.sh"
BROWSER_BOOTSTRAP = ROOT / ".github/ci/setup-browser.sh"
BROWSER_JOURNEYS = [
    "browser_archive_search_e2e.mjs",
    "browser_call_overlay_screenshot_e2e.mjs",
    "browser_meeting_note_edit_e2e.mjs",
    "browser_meeting_preparation_e2e.mjs",
    "browser_record_while_ai_busy_e2e.mjs",
    "browser_saved_meeting_e2e.mjs",
    "browser_workspace_coherence_e2e.mjs",
]


class CentralMacPreflightContractTests(unittest.TestCase):
    def test_source_actions_never_schedule_the_central_runner_directly(self) -> None:
        source = PREFLIGHT.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: macos-14", source)
        self.assertNotIn("runs-on: [self-hosted", source)
        self.assertIn("repos/$CENTRAL_REPO/dispatches", source)
        self.assertIn("-f event_type=run-ci", source)
        self.assertIn('client_payload[sha]=$SOURCE_SHA', source)

    def test_central_result_is_required_from_fresh_exact_sha_status(self) -> None:
        source = PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn("statuses: read", source)
        self.assertIn("CENTRAL_DISPATCH_TOKEN", source)
        self.assertIn('PR_HEAD_REPO" != "$SOURCE_REPO', source)
        self.assertIn('status_endpoint="repos/$SOURCE_REPO/commits/$SOURCE_SHA/statuses?per_page=100"', source)
        self.assertIn(".id > $baseline", source)
        self.assertIn('if [[ "$state" == "success" ]]', source)
        self.assertIn('elif [[ "$state" == "failure" || "$state" == "error" ]]', source)
        self.assertIn("No successful central Mac result within 55 minutes", source)

    def test_mac_entrypoint_runs_full_source_and_browser_gates(self) -> None:
        source = LOCAL_TEST.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", source)
        self.assertIn("git rev-parse HEAD", source)
        self.assertIn('uv sync --all-extras --frozen --python 3.12', source)
        self.assertIn('pnpm run lint', source)
        self.assertIn('pnpm exec tsc --noEmit', source)
        self.assertIn('python -m unittest discover -s test -v', source)
        self.assertIn('source .github/ci/setup-browser.sh', source)
        self.assertIn('node scripts/browser_meeting_ui_e2e.mjs', source)
        self.assertNotIn('brew install', source)
        self.assertNotIn('npm install --global', source)

    def test_browser_dependencies_are_isolated_and_explicit(self) -> None:
        source = BROWSER_BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('mktemp -d', source)
        self.assertIn("trap 'rm -rf", source)
        self.assertIn('chrome-for-testing-public/', source)
        self.assertIn("export CHROMEWEBDRIVER", source)
        self.assertIn("export CI_CHROME_BINARY", source)
        self.assertIn('export CHROME_BINARY="$CI_CHROME_BINARY"', source)
        self.assertIn("maxRetries: 12", (ROOT / "scripts/browser_activities_e2e.mjs").read_text(encoding="utf-8"))
        for journey in BROWSER_JOURNEYS:
            with self.subTest(journey=journey):
                content = (ROOT / "scripts" / journey).read_text(encoding="utf-8")
                self.assertIn("process.env.CI_CHROME_BINARY", content)


if __name__ == "__main__":
    unittest.main()
