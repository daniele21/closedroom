from __future__ import annotations

import copy
from typing import Any

from local_asr_server.structured_note_edits import (
    effective_generated,
    ensure_editable_structured_notes,
    prepare_structured_notes_revision,
)
from local_asr_server.structured_notes import (
    STRUCTURED_NOTES_SCHEMA_ID,
    STRUCTURED_NOTES_SCHEMA_VERSION,
    legacy_projection_results,
)


LEGACY_DEFAULT_ANALYSIS_TYPES = (
    "meeting_brief",
    "action_items",
    "decisions",
    "risks_blockers",
)


def is_structured_notes_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    schema = result.get("schema")
    if not isinstance(schema, dict):
        return False
    return (
        schema.get("id") == STRUCTURED_NOTES_SCHEMA_ID
        and schema.get("version") == STRUCTURED_NOTES_SCHEMA_VERSION
        and isinstance(result.get("generated"), dict)
    )


def _history_key(run: dict[str, Any]) -> tuple[str, str]:
    if run.get("transcription_id"):
        return "transcription", str(run["transcription_id"])
    return str(run.get("scope_type") or "scope"), str(run.get("scope_id") or "")


def _decorate_history(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    decorated: dict[str, dict[str, Any]] = {}
    previous_by_scope: dict[tuple[str, str], dict[str, Any]] = {}
    for run in sorted(runs, key=lambda item: (item.get("created_at") or 0, str(item.get("id") or ""))):
        item = copy.deepcopy(run)
        result = item.get("result")
        if item.get("status") != "completed" or not is_structured_notes_result(result):
            decorated[str(item.get("id"))] = item
            continue
        key = _history_key(item)
        previous = previous_by_scope.get(key)
        if previous is not None and "user_edits" not in result:
            editable = prepare_structured_notes_revision(
                result,
                run_id=str(item["id"]),
                previous_run=previous,
            )
        else:
            editable = ensure_editable_structured_notes(result, run_id=str(item["id"]))
            if previous is not None and not isinstance(result.get("revision"), dict):
                previous_revision = (previous.get("result") or {}).get("revision") or {}
                number = previous_revision.get("number") if isinstance(previous_revision.get("number"), int) else 1
                editable["revision"] = {
                    "number": number + 1,
                    "run_id": str(item["id"]),
                    "supersedes_run_id": previous.get("id"),
                }
        item["result"] = editable
        item["result_markdown"] = editable.get("markdown")
        decorated[str(item["id"])] = item
        previous_by_scope[key] = item
    return decorated


def _projection_edit_kind(analysis_type: str) -> str | None:
    if analysis_type == "action_items":
        return "action"
    if analysis_type == "decisions":
        return "decision"
    return None


def _filtered_edit_metadata(result: dict[str, Any], analysis_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kind = _projection_edit_kind(analysis_type)
    edits = result.get("user_edits") or []
    conflicts = result.get("conflicts") or []
    if kind is None:
        return copy.deepcopy(edits), copy.deepcopy(conflicts)
    return (
        [copy.deepcopy(edit) for edit in edits if isinstance(edit, dict) and edit.get("item_kind") == kind],
        [copy.deepcopy(conflict) for conflict in conflicts if isinstance(conflict, dict) and conflict.get("item_kind") == kind],
    )


def expand_analysis_run(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Project one real v2 run into stable legacy read views without new jobs."""
    result = run.get("result")
    if run.get("status") != "completed" or not is_structured_notes_result(result):
        return [run]

    editable = ensure_editable_structured_notes(result, run_id=str(run["id"]))
    effective_source = copy.deepcopy(editable)
    effective_source["generated"] = effective_generated(editable, run_id=str(run["id"]))
    projections = legacy_projection_results(editable)
    effective_projections = legacy_projection_results(effective_source)
    expanded: list[dict[str, Any]] = []
    for analysis_type in LEGACY_DEFAULT_ANALYSIS_TYPES:
        projection = copy.deepcopy(projections[analysis_type])
        effective_projection = effective_projections[analysis_type]
        edits, conflicts = _filtered_edit_metadata(editable, analysis_type)
        projection["revision"] = copy.deepcopy(editable.get("revision"))
        projection["user_edits"] = edits
        projection["conflicts"] = conflicts
        if analysis_type == "meeting_brief":
            projection["effective"] = copy.deepcopy(editable.get("effective") or editable.get("generated") or {})
            projection["action_items"] = effective_projection.get("action_items") or []
            projection["key_points"] = effective_projection.get("key_points") or []
        else:
            projection["effective"] = copy.deepcopy(effective_projection.get("generated") or {})
        projection["markdown"] = effective_projection.get("markdown") or projection.get("markdown")
        item = {
            **run,
            "result": projection,
            "result_markdown": projection.get("markdown"),
            "source_run_id": run["id"],
        }
        if analysis_type != "meeting_brief":
            item.update(
                {
                    "id": f"{run['id']}::{analysis_type}",
                    "job_id": None,
                    "analysis_type": analysis_type,
                    "template_id": analysis_type,
                    "template_version": "v2-projection",
                    "prompt_version": f"{run.get('prompt_version') or 'meeting_notes_shared_v2'}:projection",
                    "virtual_projection": True,
                }
            )
        expanded.append(item)
    return expanded


def expand_analysis_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated = _decorate_history(runs)
    expanded: list[dict[str, Any]] = []
    for run in runs:
        source = decorated.get(str(run.get("id")), run)
        expanded.extend(expand_analysis_run(source))
    return expanded
