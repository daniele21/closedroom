from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MEETING_PAGE = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
MEETING_ACCESSORIES = ROOT / "frontend" / "src" / "hooks" / "useMeetingAccessories.ts"


class FrontendMeetingFastOpenContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = MEETING_PAGE.read_text(encoding="utf-8")
        self.accessories = MEETING_ACCESSORIES.read_text(encoding="utf-8")

    def test_core_load_is_independent_from_accessory_routes(self) -> None:
        start = self.source.index("const load = () => {")
        end = self.source.index("\n  useEffect(() => {", start)
        core_load = self.source[start:end]

        self.assertIn("ApiClient.getMeeting(recordingId)", core_load)
        self.assertNotIn("ApiClient.getMeetingDiagnostics", core_load)
        self.assertNotIn("ApiClient.recordingVisualFrames", core_load)
        self.assertNotIn("Promise.all", core_load)

    def test_diagnostics_and_visual_routes_are_disclosure_driven(self) -> None:
        self.assertIn("if (!detailsOpen", self.source)
        self.assertIn("useMeetingAccessories", self.source)
        self.assertIn("ApiClient.getMeetingDiagnostics(recordingId)", self.accessories)
        self.assertIn("activeTab !== 'analysis'", self.source)
        self.assertIn("ApiClient.recordingVisualFrames(recordingId)", self.accessories)
        self.assertIn("visualResultAvailable && activeTab === 'analysis'", self.source)
        self.assertIn("visualResultAvailable && selectedScreenshot !== null", self.source)
        self.assertIn("selectedScreenshotKey?.meetingId === recordingId", self.source)
        self.assertIn("setSelectedScreenshotKey({ meetingId: recordingId, id: shot.screenshot_id })", self.source)
        self.assertNotIn("keyMomentVisualRequested", self.source)
        self.assertIn("visualData?.source_validity?.status === 'stale'", self.source)

    def test_stale_core_loads_are_ignored_and_terminal_reloads_are_coalesced(self) -> None:
        self.assertIn("loadInFlightRef", self.source)
        self.assertIn("if (activeLoad?.key === key)", self.source)
        self.assertIn("activeLoad.queued = true", self.source)
        self.assertIn("if (loadInFlightRef.current !== request) return;", self.source)
        self.assertIn("if (request.queued) void load();", self.source)
        self.assertIn("loadInFlightRef.current = null", self.source)

    def test_accessory_failures_have_local_retry_state(self) -> None:
        self.assertIn("diagnosticsError", self.source)
        self.assertIn("visualFramesError", self.source)
        self.assertIn("onClick={loadDiagnostics}", self.source)
        self.assertIn("onClick={loadVisualFrames}", self.source)


if __name__ == "__main__":
    unittest.main()
