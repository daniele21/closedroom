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
        self.assertIn("await prepareMeetingNotes(meeting.id, requestedIncludeScreenshots)", page)
        self.assertIn("latestPreparation?.result?.include_screenshots", page)
        self.assertIn("onClick={startPreparation}", page)
        self.assertIn("'Trascrivi e riassumi' : 'Transcribe and summarize'", page)
        self.assertIn("'Crea sintesi e azioni' : 'Create summary and actions'", page)

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

    def test_audio_analysis_is_shell_owned_and_server_orchestrated(self) -> None:
        page = (ROOT / "frontend/src/pages/AnalysisPage.tsx").read_text(encoding="utf-8")
        hook = (ROOT / "frontend/src/hooks/useAudioImports.ts").read_text(encoding="utf-8")
        route = (ROOT / "src/local_asr_server/routers/workspace.py").read_text(encoding="utf-8")
        self.assertIn("audioImports.startAnalysis(importedFile", page)
        self.assertNotIn("ApiClient.transcribe(formData)", page)
        self.assertIn("ApiClient.createAudioAnalysisPreparation(source.id, options, analysis)", hook)
        self.assertIn('"/v1/recordings/{recording_id}/audio-analysis-jobs"', route)
        self.assertIn("MeetingPreparationManager(", route)

    def test_import_uses_one_shell_owned_upload_to_durable_job_handoff(self) -> None:
        app = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
        page = (ROOT / "frontend/src/pages/TranscriptionPage.tsx").read_text(encoding="utf-8")
        hook = (ROOT / "frontend/src/hooks/useAudioImports.ts").read_text(encoding="utf-8")
        activities = (ROOT / "frontend/src/pages/ActivitiesPage.tsx").read_text(encoding="utf-8")
        client = (ROOT / "frontend/src/api/apiClient.ts").read_text(encoding="utf-8")

        self.assertIn("const audioImports = useAudioImports(", app)
        self.assertIn("audioImports={audioImports}", app)
        self.assertIn("audioImports.startTranscription(selectedFile, options)", page)
        self.assertNotIn("ApiClient.transcribe(formData", page)
        self.assertIn("ApiClient.importRecordingAudio(", hook)
        self.assertIn("ApiClient.createTranscriptionJob(source.id, options, id)", hook)
        self.assertIn("phase: 'submitting'", hook)
        self.assertIn("ApiClient.cancelRecordingAudioImport(id)", hook)
        self.assertIn("data-audio-import={upload.id}", activities)
        self.assertIn("'/v1/recordings/import-audio'", client)
        # Request IDs and file objects stay in the shell, never persistent UI storage.
        self.assertNotIn("localStorage", hook)
        self.assertNotIn("sessionStorage", hook)

    def test_inline_analysis_open_resolves_persisted_run_not_transcription(self) -> None:
        activities = (ROOT / "frontend/src/pages/ActivitiesPage.tsx").read_text(encoding="utf-8")
        analysis = (ROOT / "frontend/src/pages/AnalysisPage.tsx").read_text(encoding="utf-8")
        self.assertIn("navigateTo('analysis', `run/${job.scope_id}`)", activities)
        self.assertIn("detailId.startsWith('run/')", analysis)
        self.assertIn("ApiClient.getAnalysisRun(detailId.slice(4))", analysis)

    def test_real_sse_wire_identity_and_single_stream_owner(self) -> None:
        events = (ROOT / "frontend/src/api/jobEvents.ts").read_text(encoding="utf-8")
        activities = (ROOT / "frontend/src/hooks/useActivities.ts").read_text(encoding="utf-8")
        meeting = (ROOT / "frontend/src/hooks/useMeetingJobEvents.ts").read_text(encoding="utf-8")
        journey = (ROOT / "scripts/browser_activities_e2e.mjs").read_text(encoding="utf-8")

        self.assertIn("id: jobId", events)
        self.assertIn("progress_detail: wire.job_id", events)
        self.assertIn("? wire.event_payload ?? wire.payload ?? wire.progress_detail", events)
        self.assertIn(": wire.event_payload ?? wire.progress_detail", events)
        self.assertIn("sharedJobStreams = new Map", events)
        self.assertIn("followJobEvents(jobId, {", activities)
        self.assertIn("followJobEvents(jobId, {", meeting)
        self.assertIn("job_id: id, sequence", journey)
        self.assertIn("duplicate EventSource", journey)

    def test_recording_route_contract_is_centralized(self) -> None:
        route_helper = (ROOT / "frontend/src/utils/transcriptionRoute.ts").read_text(encoding="utf-8")
        transcription_page = (ROOT / "frontend/src/pages/TranscriptionPage.tsx").read_text(encoding="utf-8")

        self.assertIn("recordingTranscriptionRoute", route_helper)
        self.assertIn("parseRecordingTranscriptionRoute", route_helper)
        self.assertIn("parseRecordingTranscriptionRoute(detailPath)", transcription_page)
        self.assertNotIn("detailPath.startsWith('file-')", transcription_page)


if __name__ == "__main__":
    unittest.main()
