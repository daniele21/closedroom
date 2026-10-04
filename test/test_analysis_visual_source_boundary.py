from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from local_asr_server.schemas import AnalysisRequest
from local_asr_server.services.analysis_service import AnalysisService, MAX_STRUCTURED_VISUAL_SOURCES


class _Catalog:
    def __init__(self) -> None:
        self.saved = []

    def get_analysis_cache(self, _key):
        return None

    def save_analysis_cache(self, key, value):
        self.saved.append((key, value))


class _Transcriptions:
    def __init__(self) -> None:
        self.transcription = {
            "id": "trans-1",
            "recording_id": "rec-1",
            "text": "We reviewed the release.",
            "segments": [
                {"id": 1, "start": 0.0, "end": 4.0, "text": "We reviewed the release."},
            ],
        }

    def find_for_recording(self, recording_id):
        return self.transcription if recording_id == "rec-1" else None


class _Recordings:
    def __init__(self, count: int = 1) -> None:
        self.count = count

    def list_screenshots(self, recording_id):
        assert recording_id == "rec-1"
        return [
            {
                "screenshot_id": f"shot-{index}",
                "sha256": f"hash-{index}",
                "available": True,
            }
            for index in range(self.count)
        ]

    def get_visual_intelligence_v2(self, recording_id):
        assert recording_id == "rec-1"
        observations = []
        for index in range(self.count):
            observations.append({
                "observation_id": f"visual-{index}",
                "timestamp": float(index * 10),
                "task": "shared_content",
                "status": "valid",
                "content_type": "slide",
                "title": f"Roadmap {index}",
                "visible_text": [f"Milestone {index}"],
                "key_information": [f"Date {index}"],
                "confidence": 0.9,
                "source": {
                    "kind": "manual_screenshot",
                    "screenshot_id": f"shot-{index}",
                    "sha256": f"hash-{index}",
                    "display_id": 7,
                    "display_title": "Screen 1",
                },
            })
        return {
            "summary": {"generation_id": "gen-1"},
            "document": {
                "schema_version": 2,
                "generation_id": "gen-1",
                "observations": observations,
            },
        }


class AnalysisVisualSourceBoundaryTests(unittest.TestCase):
    def _service(self, *, count: int = 1) -> AnalysisService:
        services = SimpleNamespace(
            catalog=_Catalog(),
            transcriptions=_Transcriptions(),
            recordings=_Recordings(count=count),
        )
        return AnalysisService(services)

    @staticmethod
    def _body() -> AnalysisRequest:
        return AnalysisRequest(
            recording_id="rec-1",
            template_id="meeting_notes_shared",
            template_version="v2",
        )

    def test_cloud_structured_notes_never_receive_derived_visual_sources_implicitly(self) -> None:
        service = self._service()
        generated = {
            "schema": {"id": "closedroom.meeting_notes", "version": 2},
            "generated": {
                "summary": {"text": "Summary", "source_refs": []},
                "actions": [],
                "decisions": [],
                "risks": [],
            },
            "markdown": "# Meeting notes",
        }
        with patch(
            "local_asr_server.services.analysis_service.generate_structured_notes",
            return_value=generated,
        ) as generate:
            service._analyze_text(
                self._body(),
                MagicMock(),
                provider_name="gemini",
                model="gemini-3.5-flash",
                settings={},
                api_key="secret",
            )

        transcription = generate.call_args.args[1]
        self.assertNotIn("visual_sources", transcription)

    def test_local_structured_notes_receive_only_derived_textual_visual_sources(self) -> None:
        service = self._service()
        generated = {
            "schema": {"id": "closedroom.meeting_notes", "version": 2},
            "generated": {
                "summary": {"text": "Summary", "source_refs": []},
                "actions": [],
                "decisions": [],
                "risks": [],
            },
            "markdown": "# Meeting notes",
        }
        with patch(
            "local_asr_server.services.analysis_service.generate_structured_notes",
            return_value=generated,
        ) as generate:
            result = service._analyze_text(
                self._body(),
                MagicMock(),
                provider_name="nemotron_local",
                model="nemotron",
                settings={},
                api_key="",
            )

        transcription = generate.call_args.args[1]
        self.assertEqual(len(transcription["visual_sources"]), 1)
        source = transcription["visual_sources"][0]
        self.assertEqual(source["screenshot_id"], "shot-0")
        self.assertEqual(source["sha256"], "hash-0")
        self.assertNotIn("path", source)
        self.assertNotIn("image", source)
        self.assertEqual(result["source_snapshot"]["visual_sources"][0]["screenshot_id"], "shot-0")

    def test_visual_source_budget_preserves_temporal_coverage(self) -> None:
        service = self._service(count=30)
        selected = service._structured_visual_sources("rec-1")

        self.assertEqual(len(selected), MAX_STRUCTURED_VISUAL_SOURCES)
        self.assertEqual(selected[0]["screenshot_id"], "shot-0")
        self.assertEqual(selected[-1]["screenshot_id"], "shot-29")
        timestamps = [item["timestamp"] for item in selected]
        self.assertEqual(timestamps, sorted(timestamps))


if __name__ == "__main__":
    unittest.main()
