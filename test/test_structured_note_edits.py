from __future__ import annotations

import unittest

from local_asr_server.structured_note_edits import (
    StructuredNoteItemChanged,
    discard_structured_note_edit,
    edit_structured_note_item,
    ensure_editable_structured_notes,
    prepare_structured_notes_revision,
)


def structured_result(*, action_text: str = "Alex validates the release", include_action: bool = True):
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
                "text": "Release validation meeting",
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
    }


class StructuredNoteEditTests(unittest.TestCase):
    def test_edit_overlay_preserves_generated_boundary_and_survives_reload(self) -> None:
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

        self.assertEqual(edited["generated"]["actions"][0]["text"], "Alex validates the release")
        self.assertEqual(edited["effective"]["actions"][0]["text"], "Alex validates release readiness")
        self.assertEqual(edited["effective"]["actions"][0]["due"], "Monday")
        self.assertTrue(edited["effective"]["actions"][0]["user_edited"])
        self.assertEqual(edited["conflicts"], [])
        self.assertEqual(edited["user_edits"][0]["base_generated"]["text"], "Alex validates the release")
        self.assertEqual(edited["user_edits"][0]["base_generated"]["source_refs"][0]["start"], 5.0)

        reloaded = ensure_editable_structured_notes(edited, run_id="run-1")
        self.assertEqual(reloaded["effective"]["actions"][0]["text"], "Alex validates release readiness")
        self.assertEqual(reloaded["user_edits"][0]["updated_at"], 10.0)
        self.assertEqual(reloaded["user_edits"][0]["base_generated"]["source_refs"][0]["speaker"], "Alex")

    def test_regeneration_reapplies_edit_when_generated_item_is_unchanged(self) -> None:
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
        second = prepare_structured_notes_revision(
            structured_result(),
            run_id="run-2",
            previous_run={"id": "run-1", "result": first},
        )

        self.assertEqual(second["revision"], {
            "number": 2,
            "run_id": "run-2",
            "supersedes_run_id": "run-1",
        })
        self.assertEqual(second["effective"]["actions"][0]["text"], "Alex validates release readiness")
        self.assertEqual(second["conflicts"], [])
        self.assertEqual(second["user_edits"][0]["base_run_id"], "run-1")

    def test_regeneration_retains_but_does_not_apply_edit_when_generated_item_changes(self) -> None:
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
        second = prepare_structured_notes_revision(
            structured_result(action_text="Alex validates the release with QA"),
            run_id="run-2",
            previous_run={"id": "run-1", "result": first},
        )

        self.assertEqual(second["generated"]["actions"][0]["item_id"], action["item_id"])
        self.assertEqual(second["effective"]["actions"][0]["text"], "Alex validates the release with QA")
        self.assertEqual(len(second["conflicts"]), 1)
        self.assertEqual(second["conflicts"][0]["reason"], "generated_changed")
        self.assertEqual(
            second["conflicts"][0]["retained_edit"]["fields"]["text"],
            "Alex validates release readiness",
        )

    def test_regeneration_retains_missing_item_edit_as_explicit_conflict(self) -> None:
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
        second = prepare_structured_notes_revision(
            structured_result(include_action=False),
            run_id="run-2",
            previous_run={"id": "run-1", "result": first},
        )

        self.assertEqual(second["effective"]["actions"], [])
        self.assertEqual(second["conflicts"][0]["reason"], "item_missing")
        self.assertEqual(second["conflicts"][0]["item_id"], action["item_id"])
        retained = second["conflicts"][0]["retained_edit"]
        self.assertEqual(retained["fields"]["text"], "Alex validates release readiness")
        self.assertEqual(retained["base_generated"]["text"], "Alex validates the release")
        self.assertEqual(retained["base_generated"]["source_refs"][0]["start"], 5.0)

    def test_stale_edit_is_rejected_and_discard_restores_generated_value(self) -> None:
        current = ensure_editable_structured_notes(structured_result(), run_id="run-1")
        action = current["generated"]["actions"][0]
        with self.assertRaises(StructuredNoteItemChanged):
            edit_structured_note_item(
                current,
                run_id="run-1",
                item_kind="action",
                item_id=action["item_id"],
                base_generated_hash="stale-hash",
                fields={"text": "Wrong stale edit"},
            )

        edited = edit_structured_note_item(
            current,
            run_id="run-1",
            item_kind="action",
            item_id=action["item_id"],
            base_generated_hash=action["generated_hash"],
            fields={"text": "User correction"},
        )
        discarded = discard_structured_note_edit(
            edited,
            run_id="run-1",
            item_kind="action",
            item_id=action["item_id"],
        )
        self.assertEqual(discarded["user_edits"], [])
        self.assertEqual(discarded["effective"]["actions"][0]["text"], "Alex validates the release")
        self.assertEqual(discarded["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
