from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
HOOK = ROOT / "frontend" / "src" / "hooks" / "useMeetingAccessories.ts"


class MeetingAccessoryOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = PAGE.read_text(encoding="utf-8")
        self.hook = HOOK.read_text(encoding="utf-8")

    def test_accessory_loading_has_one_page_scoped_owner(self) -> None:
        self.assertIn("export function useMeetingAccessories", self.hook)
        self.assertIn("useMeetingAccessories({ recordingId, demoMode, lang })", self.page)
        self.assertIn("ApiClient.getMeetingDiagnostics", self.hook)
        self.assertIn("ApiClient.recordingScreenshots", self.hook)
        self.assertIn("ApiClient.recordingVisualFrames", self.hook)

    def test_page_no_longer_owns_accessory_generation_guards(self) -> None:
        self.assertNotIn("diagnosticsGenerationRef", self.page)
        self.assertNotIn("visualFramesGenerationRef", self.page)
        self.assertNotIn("screenshotsGenerationRef", self.page)

    def test_hook_invalidates_inflight_accessory_requests_on_context_change(self) -> None:
        self.assertIn("diagnosticsGenerationRef.current += 1", self.hook)
        self.assertIn("visualFramesGenerationRef.current += 1", self.hook)
        self.assertIn("screenshotsGenerationRef.current += 1", self.hook)


if __name__ == "__main__":
    unittest.main()
