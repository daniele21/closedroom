from __future__ import annotations

import unittest

from local_asr_server.structured_note_edits import edit_structured_note_item, ensure_editable_structured_notes
from local_asr_server.structured_notes_projection import expand_analysis_runs


def result(action_text: str = "Alex validates the release"):
    return {
        "schema": {"id": "closedroom.meeting_notes", "version": 2},
        "generated": {
            "summary": {"text": "Release review", "source_refs": [{"segment_id": 0, "start": 0.0}]},
            "actions": [{
                "text": action_text,
                "owner": "Alex",
                "due": "Friday",
                "status": None,
                "source_refs": [{"segment_id": 1, "start": 5.0, "speaker": "Alex"}],
            }],
            "decisions": [{
                "text": "Ship after validation",
                "rationale": None,
                "impact": None,
                "source_refs": [{"segment_id": 2, "start": 12.0, "speaker": "Sam"}],
            }],
            "risks": [],
        },
        "markdown": "generated markdown",
    }


def run(run_id: str, created_at: float, payload: dict):
    return {
        "id": run_id,
        "job_id": f"job-{run_id}",
        "scope_type": "transcription",
        "scope_id": "trans-1",
        "transcription_id": "trans-1",
        "recording_id": "rec-1",
        "analysis_type": "meeting_brief",
        "template_id": "meeting_notes_shared",
        "template_version": "v2",
        "prompt_version": "meeting_notes_shared_v2",
        "status": "completed",
        "result": payload,
        "result_markdown": payload.get("markdown"),
        "created_at": created_at,
    }


class StructuredNoteProjectionEditTests(unittest.TestCase):
    def test_history_projects_safe_edit_into_next_revision_without_mutating_generated(self) -> None:
        first = ensure_editable_structured_notes(result(), run_id="run-1")
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
        items = expand_analysis_runs([
            run("run-2", 2.0, result()),
            run("run-1", 1.0, first),
        ])
        latest_action_view = next(item for item in items if item["id"] == "run-2::action_items")

        self.assertEqual(latest_action_view["result"]["revision"]["number"], 2)
        self.assertEqual(latest_action_view["result"]["generated"]["actions"][0]["text"], "Alex validates the release")
        self.assertEqual(latest_action_view["result"]["effective"]["actions"][0]["text"], "Alex validates release readiness")
        self.assertIn("Alex validates release readiness", latest_action_view["result_markdown"])
        self.assertEqual(latest_action_view["result"]["conflicts"], [])

    def test_history_surfaces_changed_generation_as_conflict(self) -> None:
        first = ensure_editable_structured_notes(result(), run_id="run-1")
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
        items = expand_analysis_runs([
            run("run-2", 2.0, result("Alex validates the release with QA")),
            run("run-1", 1.0, first),
        ])
        latest_action_view = next(item for item in items if item["id"] == "run-2::action_items")

        self.assertEqual(latest_action_view["result"]["revision"]["supersedes_run_id"], "run-1")
        self.assertEqual(latest_action_view["result"]["effective"]["actions"][0]["text"], "Alex validates the release with QA")
        self.assertEqual(latest_action_view["result"]["conflicts"][0]["reason"], "generated_changed")
        self.assertEqual(latest_action_view["result"]["user_edits"][0]["fields"]["text"], "Alex validates release readiness")

    def test_explicit_empty_edit_set_on_new_revision_does_not_reinherit_old_edit(self) -> None:
        first = ensure_editable_structured_notes(result(), run_id="run-1")
        action = first["generated"]["actions"][0]
        first = edit_structured_note_item(
            first,
            run_id="run-1",
            item_kind="action",
            item_id=action["item_id"],
            base_generated_hash=action["generated_hash"],
            fields={"text": "User correction"},
            now=10.0,
        )
        second = ensure_editable_structured_notes(result(), run_id="run-2")
        second["revision"] = {"number": 2, "run_id": "run-2", "supersedes_run_id": "run-1"}
        second["user_edits"] = []
        items = expand_analysis_runs([
            run("run-2", 2.0, second),
            run("run-1", 1.0, first),
        ])
        latest_action_view = next(item for item in items if item["id"] == "run-2::action_items")

        self.assertEqual(latest_action_view["result"]["user_edits"], [])
        self.assertEqual(latest_action_view["result"]["effective"]["actions"][0]["text"], "Alex validates the release")


if __name__ == "__main__":
    unittest.main()
