from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MEETING_PAGE = ROOT / "frontend" / "src" / "pages" / "MeetingDetailPage.tsx"
JOB_EVENTS = ROOT / "frontend" / "src" / "api" / "jobEvents.ts"
MEETING_HOOK = ROOT / "frontend" / "src" / "hooks" / "useMeetingJobEvents.ts"


class FrontendJobEventsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.meeting_source = MEETING_PAGE.read_text(encoding="utf-8")
        self.events_source = JOB_EVENTS.read_text(encoding="utf-8")
        self.hook_source = MEETING_HOOK.read_text(encoding="utf-8")

    def test_normal_meeting_progress_uses_job_events_without_interval_polling(self) -> None:
        self.assertIn("useMeetingJobEvents", self.meeting_source)
        self.assertNotIn("setInterval(load", self.meeting_source)
        self.assertNotIn("2500", self.meeting_source)

    def test_event_stream_is_normal_path_and_get_snapshot_is_recovery_only(self) -> None:
        self.assertIn("new EventSource", self.events_source)
        self.assertIn("source.onerror", self.events_source)
        self.assertIn("const recover = async", self.events_source)
        self.assertIn("ApiClient.getJob(jobId)", self.events_source)
        self.assertNotIn("setInterval", self.events_source)
        self.assertIn("onTerminal", self.events_source)

    def test_meeting_hook_follows_transcription_visual_and_analysis_job_ids(self) -> None:
        self.assertIn("meeting.jobs", self.hook_source)
        self.assertIn("meeting.analysis_runs", self.hook_source)
        self.assertIn("run.job_id", self.hook_source)
        self.assertIn("followJobEvents", self.hook_source)
        self.assertIn("void reloadRef.current()", self.hook_source)


if __name__ == "__main__":
    unittest.main()
