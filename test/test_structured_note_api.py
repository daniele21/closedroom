from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from local_asr_server.app_services import get_services
from local_asr_server.server import create_app
from support import deterministic_settings


def structured_result(*, action_text: str = "Alex validates the release", include_action: bool = True) -> dict:
    actions = []
    if include_action:
        actions.append({
            "text": action_text,
            "owner": "Alex",
            "due": "Friday",
            "status": None,
            "source_refs": [{"segment_id": 1, "start": 5.0, "end": 12.0, "speaker": "Alex"}],
        })
    return {
        "schema": {"id": "closedroom.meeting_notes", "version": 2},
        "generated": {
            "summary": {
                "text": "Release review",
                "source_refs": [{"segment_id": 0, "start": 0.0, "end": 5.0, "speaker": "Sam"}],
            },
            "actions": actions,
            "decisions": [{
                "text": "Ship only after validation",
                "rationale": None,
                "impact": None,
                "source_refs": [{"segment_id": 2, "start": 12.0, "end": 20.0, "speaker": "Sam"}],
            }],
            "risks": [],
        },
        "metrics": {},
        "markdown": "# Meeting notes",
    }


def create_run(catalog, *, run_id: str, created_at: float, result: dict) -> None:
    catalog.create_analysis_run({
        "id": run_id,
        "job_id": f"job-{run_id}",
        "scope_type": "transcription",
        "scope_id": "trans-1",
        "transcription_id": "trans-1",
        "recording_id": "rec-1",
        "analysis_type": "meeting_brief",
        "template_id": "meeting_notes_shared",
        "template_version": "v2",
        "pipeline_run_id": f"pipeline-{run_id}",
        "provider": "mock",
        "model": "",
        "reasoning": "auto",
        "show_thinking": False,
        "json_mode": True,
        "llm_options": {},
        "prompt_version": "meeting_notes_shared_v2",
        "input_hash": "input-hash",
        "status": "completed",
        "result": result,
        "source_ids": ["rec-1", "trans-1"],
        "created_at": created_at,
        "completed_at": created_at + 1,
    })


class StructuredNoteApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        settings = deterministic_settings(root)
        self.settings_patches = [
            patch("local_asr_server.transcriptions.load_settings", return_value=settings),
            patch("local_asr_server.runtime.service_manager.load_settings", return_value=settings),
            patch("local_asr_server.services.analysis_service.load_settings", return_value=settings),
        ]
        for item in self.settings_patches:
            item.start()
        self.app = create_app(
            default_model="test-model",
            recordings_dir=root / "recordings",
            enable_auth=False,
        )
        self.client = TestClient(self.app)
        self.catalog = get_services(self.app).catalog

    def tearDown(self) -> None:
        self.client.close()
        for item in reversed(self.settings_patches):
            item.stop()
        self.temp.cleanup()

    def _create_first_run(self) -> dict:
        create_run(self.catalog, run_id="run-1", created_at=1.0, result=structured_result())
        response = self.client.get("/v1/analysis-runs/run-1")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_patch_preserves_generated_boundary_and_rejects_stale_generation(self) -> None:
        first = self._create_first_run()
        action = first["result"]["generated"]["actions"][0]

        stale = self.client.patch(
            f"/v1/analysis-runs/run-1/items/action/{action['item_id']}",
            json={"base_generated_hash": "stale", "fields": {"text": "Stale overwrite"}},
        )
        self.assertEqual(stale.status_code, 409)

        edited = self.client.patch(
            f"/v1/analysis-runs/run-1/items/action/{action['item_id']}",
            json={
                "base_generated_hash": action["generated_hash"],
                "fields": {"text": "Alex validates release readiness", "due": "Monday"},
            },
        )
        self.assertEqual(edited.status_code, 200)
        payload = edited.json()["result"]
        self.assertEqual(payload["generated"]["actions"][0]["text"], "Alex validates the release")
        self.assertEqual(payload["effective"]["actions"][0]["text"], "Alex validates release readiness")
        self.assertEqual(payload["effective"]["actions"][0]["due"], "Monday")
        self.assertEqual(payload["user_edits"][0]["base_generated"]["source_refs"][0]["start"], 5.0)

    def test_regenerated_item_requires_explicit_rebase_before_edit_is_applied(self) -> None:
        first = self._create_first_run()
        action = first["result"]["generated"]["actions"][0]
        edited = self.client.patch(
            f"/v1/analysis-runs/run-1/items/action/{action['item_id']}",
            json={
                "base_generated_hash": action["generated_hash"],
                "fields": {"text": "Alex validates release readiness"},
            },
        )
        self.assertEqual(edited.status_code, 200)

        create_run(
            self.catalog,
            run_id="run-2",
            created_at=2.0,
            result=structured_result(action_text="Alex validates the release with QA"),
        )
        second = self.client.get("/v1/analysis-runs/run-2")
        self.assertEqual(second.status_code, 200)
        second_result = second.json()["result"]
        self.assertEqual(second_result["revision"]["number"], 2)
        self.assertEqual(second_result["revision"]["supersedes_run_id"], "run-1")
        self.assertEqual(second_result["effective"]["actions"][0]["text"], "Alex validates the release with QA")
        self.assertEqual(second_result["conflicts"][0]["reason"], "generated_changed")

        regenerated_action = second_result["generated"]["actions"][0]
        rebased = self.client.patch(
            f"/v1/analysis-runs/run-2/items/action/{regenerated_action['item_id']}",
            json={
                "base_generated_hash": regenerated_action["generated_hash"],
                "fields": {"text": "Alex validates release readiness"},
            },
        )
        self.assertEqual(rebased.status_code, 200)
        rebased_result = rebased.json()["result"]
        self.assertEqual(rebased_result["conflicts"], [])
        self.assertEqual(rebased_result["effective"]["actions"][0]["text"], "Alex validates release readiness")
        self.assertEqual(rebased_result["user_edits"][0]["base_run_id"], "run-2")

    def test_missing_item_conflict_keeps_source_until_explicit_discard(self) -> None:
        first = self._create_first_run()
        action = first["result"]["generated"]["actions"][0]
        edited = self.client.patch(
            f"/v1/analysis-runs/run-1/items/action/{action['item_id']}",
            json={
                "base_generated_hash": action["generated_hash"],
                "fields": {"text": "Alex validates release readiness"},
            },
        )
        self.assertEqual(edited.status_code, 200)

        create_run(
            self.catalog,
            run_id="run-2",
            created_at=2.0,
            result=structured_result(include_action=False),
        )
        second = self.client.get("/v1/analysis-runs/run-2")
        self.assertEqual(second.status_code, 200)
        conflict = second.json()["result"]["conflicts"][0]
        self.assertEqual(conflict["reason"], "item_missing")
        self.assertEqual(conflict["retained_edit"]["fields"]["text"], "Alex validates release readiness")
        self.assertEqual(conflict["retained_edit"]["base_generated"]["source_refs"][0]["start"], 5.0)

        discarded = self.client.delete(
            f"/v1/analysis-runs/run-2/items/action/{conflict['item_id']}/edit"
        )
        self.assertEqual(discarded.status_code, 200)
        self.assertEqual(discarded.json()["result"]["conflicts"], [])
        self.assertEqual(discarded.json()["result"]["user_edits"], [])

        reloaded = self.client.get("/v1/analysis-runs/run-2")
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.json()["result"]["conflicts"], [])
        self.assertEqual(reloaded.json()["result"]["user_edits"], [])


if __name__ == "__main__":
    unittest.main()
