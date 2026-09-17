from __future__ import annotations

import copy
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from local_asr_server.analysis_jobs import AnalysisJobManager
from local_asr_server.analysis_templates import list_templates
from local_asr_server.jobs import JobStore
from local_asr_server.schemas import AnalysisPipelineRequest, AnalysisRequest
from local_asr_server.services.analysis_service import AnalysisService
from local_asr_server.structured_notes import STRUCTURED_NOTES_TEMPLATE_ID
from local_asr_server.structured_notes_projection import expand_analysis_run
from support import deterministic_settings


class FakeCatalog:
    def __init__(self) -> None:
        self.runs = {}
        self.cache = {}

    def create_analysis_run(self, run):
        self.runs[run["id"]] = copy.deepcopy(run)
        return copy.deepcopy(run)

    def get_analysis_run(self, run_id):
        run = self.runs.get(run_id)
        return copy.deepcopy(run) if run else None

    def get_analysis_cache(self, key):
        value = self.cache.get(key)
        return copy.deepcopy(value) if value is not None else None

    def save_analysis_cache(self, key, result):
        self.cache[key] = copy.deepcopy(result)


class FakeTranscriptions:
    def __init__(self, transcription):
        self.transcription = copy.deepcopy(transcription)
        self.saved = []

    def get(self, transcription_id):
        if transcription_id != self.transcription["id"]:
            raise FileNotFoundError(transcription_id)
        return copy.deepcopy(self.transcription)

    def find_for_recording(self, recording_id):
        if recording_id == self.transcription.get("recording_id"):
            return copy.deepcopy(self.transcription)
        return None

    def save_analysis(self, transcription_id, result):
        self.saved.append((transcription_id, copy.deepcopy(result)))
        return copy.deepcopy(self.transcription)


class CountingStructuredProvider:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, text, prompt=None, temperature=None):
        self.calls += 1
        match = re.search(r"\[S([^\s\]]+)", text)
        segment_id = int(match.group(1)) if match and match.group(1).isdigit() else 0
        return {
            "generated": {
                "summary": {
                    "text": "Supported summary",
                    "source_refs": [{"segment_id": segment_id}],
                },
                "actions": [],
                "decisions": [],
                "risks": [],
            }
        }


def transcript_fixture():
    return {
        "id": "trans-1",
        "recording_id": "rec-1",
        "text": "Alex will validate the release.",
        "segments": [
            {
                "id": 0,
                "start": 1.0,
                "end": 4.0,
                "speaker_label": "Alex",
                "text": "Alex will validate the release.",
            }
        ],
    }


class SharedAnalysisPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = JobStore(root / "jobs.db")
        self.catalog = FakeCatalog()
        self.transcriptions = FakeTranscriptions(transcript_fixture())
        self.services = SimpleNamespace(
            catalog=self.catalog,
            transcriptions=self.transcriptions,
        )
        self.settings = deterministic_settings(root)
        self.settings["llm_provider"] = "mock"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_pipeline_uses_one_shared_v2_job(self) -> None:
        manager = AnalysisJobManager(self.services, self.store)
        body = AnalysisPipelineRequest(text="Representative meeting", pipeline_id="meeting_default")

        with patch("local_asr_server.analysis_jobs.load_settings", return_value=self.settings), patch.object(
            manager, "_run", return_value=None
        ):
            created = manager.create_pipeline(body)

        self.assertEqual(len(created["jobs"]), 1)
        run = self.catalog.get_analysis_run(created["jobs"][0]["analysis_run_id"])
        self.assertEqual(run["template_id"], STRUCTURED_NOTES_TEMPLATE_ID)
        self.assertEqual(run["template_version"], "v2")
        self.assertEqual(run["analysis_type"], "meeting_brief")

    def test_explicit_analysis_types_keep_legacy_multi_job_path(self) -> None:
        manager = AnalysisJobManager(self.services, self.store)
        body = AnalysisPipelineRequest(
            text="Representative meeting",
            pipeline_id="meeting_default",
            analysis_types=["action_items", "decisions"],
        )

        with patch("local_asr_server.analysis_jobs.load_settings", return_value=self.settings), patch.object(
            manager, "_run", return_value=None
        ):
            created = manager.create_pipeline(body)

        self.assertEqual(len(created["jobs"]), 2)
        template_ids = {
            self.catalog.get_analysis_run(item["analysis_run_id"])["template_id"]
            for item in created["jobs"]
        }
        self.assertEqual(template_ids, {"action_items", "decisions"})

    def test_pipeline_identity_versions_shared_default_but_not_public_template_list(self) -> None:
        manager = AnalysisJobManager(self.services, self.store)
        with patch("local_asr_server.analysis_jobs.load_settings", return_value=self.settings):
            identity = manager.pipeline_identity(AnalysisPipelineRequest(text="x", pipeline_id="meeting_default"))

        self.assertEqual(identity["templates"], [
            {"id": STRUCTURED_NOTES_TEMPLATE_ID, "analysis_type": "meeting_brief", "version": "v2"}
        ])
        self.assertNotIn(STRUCTURED_NOTES_TEMPLATE_ID, {item["id"] for item in list_templates()})

    def test_structured_cache_identity_includes_source_segments(self) -> None:
        provider = CountingStructuredProvider()
        service = AnalysisService(self.services)
        body = AnalysisRequest(
            transcription_id="trans-1",
            template_id=STRUCTURED_NOTES_TEMPLATE_ID,
            template_version="v2",
            prompt="CLOSEDROOM_MEETING_NOTES_V2",
            analysis_type="meeting_brief",
        )

        with patch("local_asr_server.services.analysis_service.load_settings", return_value=self.settings), patch(
            "local_asr_server.services.analysis_service.LLMService.get_provider", return_value=provider
        ):
            first = service.analyze(body)
            second = service.analyze(body)
            self.transcriptions.transcription["segments"][0]["start"] = 2.0
            third = service.analyze(body)

        self.assertEqual(provider.calls, 2)
        self.assertEqual(first["schema"]["version"], 2)
        self.assertEqual(second, first)
        self.assertEqual(third["generated"]["summary"]["source_refs"][0]["start"], 2.0)
        self.assertGreaterEqual(len(self.transcriptions.saved), 3)
        _transcription_id, legacy = self.transcriptions.saved[-1]
        self.assertEqual(legacy["summary"], "Supported summary")
        self.assertIn("action_items", legacy)

    def test_one_structured_run_projects_to_four_legacy_read_views(self) -> None:
        service = AnalysisService(self.services)
        provider = CountingStructuredProvider()
        body = AnalysisRequest(
            transcription_id="trans-1",
            template_id=STRUCTURED_NOTES_TEMPLATE_ID,
            template_version="v2",
            prompt="CLOSEDROOM_MEETING_NOTES_V2",
            analysis_type="meeting_brief",
        )
        with patch("local_asr_server.services.analysis_service.load_settings", return_value=self.settings), patch(
            "local_asr_server.services.analysis_service.LLMService.get_provider", return_value=provider
        ):
            result = service.analyze(body)

        run = {
            "id": "run-1",
            "job_id": "job-1",
            "analysis_type": "meeting_brief",
            "template_id": STRUCTURED_NOTES_TEMPLATE_ID,
            "template_version": "v2",
            "prompt_version": "meeting_notes_shared_v2",
            "status": "completed",
            "result": result,
            "result_markdown": result["markdown"],
            "created_at": 1.0,
        }
        expanded = expand_analysis_run(run)

        self.assertEqual(
            [item["analysis_type"] for item in expanded],
            ["meeting_brief", "action_items", "decisions", "risks_blockers"],
        )
        self.assertEqual(expanded[0]["id"], "run-1")
        self.assertEqual(expanded[1]["id"], "run-1::action_items")
        self.assertIsNone(expanded[1]["job_id"])
        self.assertTrue(expanded[1]["virtual_projection"])


if __name__ == "__main__":
    unittest.main()
