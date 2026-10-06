from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MEETING = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
MEETING_ACCESSORIES = ROOT / "frontend" / "src" / "hooks" / "useMeetingAccessories.ts"
CLIENT = ROOT / "frontend" / "src" / "api" / "visualJobs.ts"
NEW_MEETING = ROOT / "frontend" / "src" / "pages" / "NewRecordingPage.tsx"
VITE_CONFIG = ROOT / "frontend" / "vite.config.ts"


class FrontendVisualOnDemandContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.meeting = MEETING.read_text(encoding="utf-8")
        self.meeting_accessories = MEETING_ACCESSORIES.read_text(encoding="utf-8")
        self.client = CLIENT.read_text(encoding="utf-8")
        self.new_meeting = NEW_MEETING.read_text(encoding="utf-8")
        self.vite_config = VITE_CONFIG.read_text(encoding="utf-8")

    def test_meeting_only_offers_analysis_when_screen_context_was_captured(self) -> None:
        self.assertIn("useMeetingAccessories", self.meeting)
        self.assertIn("ApiClient.recordingVisualFrames(recordingId)", self.meeting_accessories)
        self.assertIn("const visualEvidenceCount = visualFrameCount + availableScreenshotCount", self.meeting)
        self.assertIn("visualData?.source_validity?.status === 'stale'", self.meeting)
        self.assertIn("visualResultAvailable && !visualSourcesStale", self.meeting)
        self.assertIn("visualEvidenceCount > 0 && !visualEnabled", self.meeting)
        self.assertIn("visualEvidenceCount <= 0", self.meeting)
        self.assertIn("createVisualIntelligenceJob(meeting.id)", self.meeting)
        self.assertIn("Analizza contesto schermo", self.meeting)
        self.assertIn('variant="secondary"', self.meeting)

    def test_visual_job_client_uses_dedicated_on_demand_endpoints(self) -> None:
        self.assertIn("/visual-intelligence-jobs", self.client)
        self.assertIn("method: 'POST'", self.client)
        self.assertIn("cancelVisualIntelligenceJob", self.client)

    def test_vite_dev_proxy_routes_v2_visual_intelligence_to_backend(self) -> None:
        self.assertIn("'/v1':", self.vite_config)
        self.assertIn("'/v2':", self.vite_config)
        self.assertGreaterEqual(self.vite_config.count("process.env.BACKEND_PORT"), 3)

    def test_new_meeting_keeps_visual_context_explicit_and_does_not_mutate_settings(self) -> None:
        self.assertIn("showScreenContext", self.new_meeting)
        self.assertIn("ApiClient.captureWindows()", self.new_meeting)
        self.assertIn("visualWindowId", self.new_meeting)
        self.assertIn("Contesto schermo (opzionale)", self.new_meeting)
        self.assertNotIn("visual_intelligence_enabled", self.new_meeting)
        self.assertNotIn("updateSettings({ visual", self.new_meeting)


if __name__ == "__main__":
    unittest.main()
