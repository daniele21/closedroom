from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "frontend/src/pages/AnalysisPage.tsx"
APP = ROOT / "frontend/src/App.tsx"


class CanonicalMeetingFromExpertAnalysisTests(unittest.TestCase):
    def test_linked_transcript_offers_the_canonical_saved_meeting(self) -> None:
        source = ANALYSIS.read_text(encoding="utf-8")
        self.assertIn("navigateTo('meeting', selectedTr.recording_id)", source)
        self.assertIn("selectedTr.recording_id && (", source)
        self.assertIn('data-analysis-open-meeting="true"', source)
        self.assertIn("Open full meeting", source)

    def test_unlinked_import_and_expert_analysis_are_not_redirected(self) -> None:
        source = ANALYSIS.read_text(encoding="utf-8")
        app = APP.read_text(encoding="utf-8")
        self.assertIn("onClick={() => fileInputRef.current?.click()}", source)
        self.assertIn("!transcriptions.find(t => t.id === selectedTranscriptionId)?.recording_id", source)
        self.assertIn("case 'analysis':", app)
        self.assertIn("return <AnalysisPage", app)


if __name__ == "__main__":
    unittest.main()
