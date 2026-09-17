import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendTranscriptionWorkflowTests(unittest.TestCase):
    def test_meeting_uses_one_action_default_transcription(self) -> None:
        page = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")

        self.assertIn("const startDefaultTranscription = async () =>", page)
        self.assertIn("ApiClient.createTranscriptionJob(meeting.id, {", page)
        self.assertIn("visual_intelligence_enabled: false", page)
        self.assertIn("onClick={startDefaultTranscription}", page)

        default_action = page.split("const startDefaultTranscription = async () =>", 1)[1].split(
            "const openAnalysisSetup", 1
        )[0]
        for technical_override in (
            "model:",
            "language:",
            "asr_provider:",
            "diarization_provider:",
            "speechmatics_model:",
        ):
            self.assertNotIn(technical_override, default_action)

    def test_meeting_keeps_technical_transcription_as_advanced_path(self) -> None:
        page = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")

        self.assertIn("const openAdvancedTranscription = () =>", page)
        self.assertIn("recordingTranscriptionRoute(meeting.id", page)
        self.assertIn("openAdvancedTranscription();", page)
        self.assertNotIn("TranscriptionModelModal", page)

    def test_default_notes_preparation_is_one_action_and_deep_options_remain_advanced(self) -> None:
        page = (ROOT / "frontend/src/pages/MeetingDetailPage.tsx").read_text(encoding="utf-8")

        self.assertIn("const startPreparation = async () =>", page)
        self.assertIn("await prepareMeetingNotes(meeting.id)", page)
        self.assertIn("onClick={startPreparation}", page)
        self.assertIn("'Prepara note' : 'Prepare notes'", page)

        default_action = page.split("const startPreparation = async () =>", 1)[1].split(
            "const startVisualContextAnalysis", 1
        )[0]
        for technical_override in (
            "pipeline_id:",
            "model:",
            "temperature:",
            "reasoning:",
            "max_output_tokens:",
        ):
            self.assertNotIn(technical_override, default_action)

        self.assertIn("startPipeline('meeting_default');", page)
        self.assertIn("'Rigenera solo analisi' : 'Regenerate analysis only'", page)
        self.assertIn("openAnalysisSetup('meeting_deep')", page)
        self.assertIn("<AnalysisSetupModal", page)

    def test_recording_route_contract_is_centralized(self) -> None:
        route_helper = (ROOT / "frontend/src/utils/transcriptionRoute.ts").read_text(encoding="utf-8")
        transcription_page = (ROOT / "frontend/src/pages/TranscriptionPage.tsx").read_text(encoding="utf-8")

        self.assertIn("recordingTranscriptionRoute", route_helper)
        self.assertIn("parseRecordingTranscriptionRoute", route_helper)
        self.assertIn("parseRecordingTranscriptionRoute(detailPath)", transcription_page)
        self.assertNotIn("detailPath.startsWith('file-')", transcription_page)


if __name__ == "__main__":
    unittest.main()
