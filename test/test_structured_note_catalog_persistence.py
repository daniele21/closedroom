from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_asr_server.catalog import CatalogStore
from local_asr_server.structured_note_edits import edit_structured_note_item, ensure_editable_structured_notes
from local_asr_server.structured_notes_projection import expand_analysis_runs


def structured_result() -> dict:
    return {
        "schema": {"id": "closedroom.meeting_notes", "version": 2},
        "generated": {
            "summary": {
                "text": "Release review",
                "source_refs": [{"segment_id": 0, "start": 0.0, "end": 5.0, "speaker": "Sam"}],
            },
            "actions": [{
                "text": "Alex validates the release",
                "owner": "Alex",
                "due": "Friday",
                "status": None,
                "source_refs": [{"segment_id": 1, "start": 5.0, "end": 12.0, "speaker": "Alex"}],
            }],
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


def create_run(store: CatalogStore, *, run_id: str, created_at: float, result: dict) -> None:
    store.create_analysis_run({
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


class StructuredNoteCatalogPersistenceTests(unittest.TestCase):
    def test_user_edit_survives_catalog_reopen_without_separate_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closedroom.db"
            store = CatalogStore(db_path)
            initial = ensure_editable_structured_notes(structured_result(), run_id="run-1")
            action = initial["generated"]["actions"][0]
            edited = edit_structured_note_item(
                initial,
                run_id="run-1",
                item_kind="action",
                item_id=action["item_id"],
                base_generated_hash=action["generated_hash"],
                fields={"text": "Alex validates release readiness", "due": "Monday"},
                now=10.0,
            )
            create_run(store, run_id="run-1", created_at=1.0, result=edited)

            reopened = CatalogStore(db_path)
            persisted = reopened.get_analysis_run("run-1")
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["result"]["generated"]["actions"][0]["text"], "Alex validates the release")
            self.assertEqual(persisted["result"]["user_edits"][0]["fields"]["text"], "Alex validates release readiness")

            projected = expand_analysis_runs(reopened.list_analysis_runs(transcription_id="trans-1"))
            action_view = next(item for item in projected if item["id"] == "run-1::action_items")
            self.assertEqual(action_view["result"]["effective"]["actions"][0]["text"], "Alex validates release readiness")
            self.assertEqual(action_view["result"]["effective"]["actions"][0]["due"], "Monday")
            self.assertEqual(action_view["result"]["conflicts"], [])

    def test_new_revision_after_reopen_retains_edit_as_conflict_when_generation_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closedroom.db"
            store = CatalogStore(db_path)
            first = ensure_editable_structured_notes(structured_result(), run_id="run-1")
            action = first["generated"]["actions"][0]
            first = edit_structured_note_item(
                first,
                run_id="run-1",
                item_kind="action",
                item_id=action["item_id"],
                base_generated_hash=action["generated_hash"],
                fields={"text": "Alex validates release readiness"},
                now=10.0,
            )
            create_run(store, run_id="run-1", created_at=1.0, result=first)

            regenerated = structured_result()
            regenerated["generated"]["actions"][0]["text"] = "Alex validates the release with QA"
            create_run(CatalogStore(db_path), run_id="run-2", created_at=2.0, result=regenerated)

            reopened = CatalogStore(db_path)
            projected = expand_analysis_runs(reopened.list_analysis_runs(transcription_id="trans-1"))
            action_view = next(item for item in projected if item["id"] == "run-2::action_items")
            self.assertEqual(action_view["result"]["revision"]["number"], 2)
            self.assertEqual(action_view["result"]["revision"]["supersedes_run_id"], "run-1")
            self.assertEqual(action_view["result"]["effective"]["actions"][0]["text"], "Alex validates the release with QA")
            self.assertEqual(action_view["result"]["conflicts"][0]["reason"], "generated_changed")
            self.assertEqual(
                action_view["result"]["conflicts"][0]["retained_edit"]["fields"]["text"],
                "Alex validates release readiness",
            )


if __name__ == "__main__":
    unittest.main()
