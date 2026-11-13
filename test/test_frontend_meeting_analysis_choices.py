from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEETING = ROOT / "frontend/src/pages/MeetingDetailPage.tsx"
CHOICES = ROOT / "frontend/src/components/meeting/MeetingAnalysisChoices.tsx"


class MeetingAnalysisChoicesTests(unittest.TestCase):
    def test_only_existing_canonical_analysis_actions_are_presented(self) -> None:
        meeting = MEETING.read_text(encoding="utf-8")
        choices = CHOICES.read_text(encoding="utf-8")
        self.assertIn("<MeetingAnalysisChoices", meeting)
        self.assertIn("onPrepare={() => void startPreparation()}", meeting)
        self.assertIn("onDeepAnalysis={() => openAnalysisSetup('meeting_deep')}", meeting)
        self.assertIn("disabled={demoMode || isBusy}", meeting)
        self.assertIn("hasTranscription={Boolean(meeting.transcription)}", meeting)
        self.assertIn('data-meeting-outcome="summary"', choices)
        self.assertIn('data-meeting-outcome="deep"', choices)
        self.assertIn("disabled={disabled || !hasTranscription}", choices)
        self.assertIn("Sintesi e prossimi passi", choices)
        self.assertIn("Disponibile dopo la trascrizione.", choices)

    def test_presentation_never_owns_jobs_settings_or_network(self) -> None:
        choices = CHOICES.read_text(encoding="utf-8")
        for forbidden in ("ApiClient", "fetch(", "localStorage", "sessionStorage", "useEffect", "createAnalysisPipeline"):
            self.assertNotIn(forbidden, choices)


if __name__ == "__main__":
    unittest.main()
