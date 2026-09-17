from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any

from local_asr_server.structured_notes import (
    STRUCTURED_NOTES_SCHEMA_ID,
    STRUCTURED_NOTES_SCHEMA_VERSION,
    render_structured_notes_markdown,
)


EDITABLE_ITEM_FIELDS = {
    "action": ("text", "owner", "due", "status"),
    "decision": ("text", "rationale", "impact"),
}
ITEM_COLLECTIONS = {
    "action": "actions",
    "decision": "decisions",
    "risk": "risks",
}


class StructuredNoteEditError(ValueError):
    pass


class StructuredNoteItemNotFound(StructuredNoteEditError):
    pass


class StructuredNoteItemChanged(StructuredNoteEditError):
    pass


def is_structured_notes_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    schema = result.get("schema")
    return (
        isinstance(schema, dict)
        and schema.get("id") == STRUCTURED_NOTES_SCHEMA_ID
        and schema.get("version") == STRUCTURED_NOTES_SCHEMA_VERSION
        and isinstance(result.get("generated"), dict)
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_anchor(item: dict[str, Any]) -> str:
    refs = item.get("source_refs") or []
    identifiers = [str(ref.get("segment_id")) for ref in refs if isinstance(ref, dict) and ref.get("segment_id") is not None]
    return "|".join(sorted(identifiers))


def _stable_item_id(kind: str, item: dict[str, Any], occurrence: int) -> str:
    seed = f"{kind}|{_source_anchor(item)}|{occurrence}"
    return f"{kind}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def generated_item_hash(kind: str, item: dict[str, Any]) -> str:
    fields = ITEM_COLLECTIONS.get(kind)
    if fields is None:
        raise StructuredNoteEditError(f"Unsupported structured-note item kind: {kind}")
    payload = {
        "kind": kind,
        "text": item.get("text") or "",
        "source_refs": item.get("source_refs") or [],
    }
    for field in EDITABLE_ITEM_FIELDS.get(kind, ()):  # risks are identifiable but not editable in PRS-14.
        if field != "text":
            payload[field] = item.get(field)
    if kind == "risk":
        for field in ("severity", "impact", "next_step"):
            payload[field] = item.get(field)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _with_stable_item_identity(result: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(result)
    generated = output.setdefault("generated", {})
    for kind, collection in ITEM_COLLECTIONS.items():
        values = generated.get(collection)
        if not isinstance(values, list):
            generated[collection] = []
            continue
        occurrences: dict[str, int] = {}
        normalized: list[dict[str, Any]] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            item = copy.deepcopy(value)
            anchor = _source_anchor(item)
            occurrence = occurrences.get(anchor, 0)
            occurrences[anchor] = occurrence + 1
            item["item_id"] = _stable_item_id(kind, item, occurrence)
            item["generated_hash"] = generated_item_hash(kind, item)
            normalized.append(item)
        generated[collection] = normalized
    return output


def _current_item(result: dict[str, Any], kind: str, item_id: str) -> dict[str, Any] | None:
    collection = ITEM_COLLECTIONS.get(kind)
    if collection is None:
        return None
    for item in (result.get("generated") or {}).get(collection) or []:
        if isinstance(item, dict) and item.get("item_id") == item_id:
            return item
    return None


def _normalize_patch(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    allowed = set(EDITABLE_ITEM_FIELDS.get(kind, ()))
    if not allowed:
        raise StructuredNoteEditError("Only actions and decisions are editable")
    unknown = set(fields) - allowed
    if unknown:
        raise StructuredNoteEditError(f"Unsupported edit fields for {kind}: {', '.join(sorted(unknown))}")
    if not fields:
        raise StructuredNoteEditError("At least one edit field is required")
    patch: dict[str, Any] = {}
    for field, value in fields.items():
        if value is None:
            patch[field] = None
            continue
        if not isinstance(value, str):
            raise StructuredNoteEditError(f"Edit field {field} must be a string or null")
        normalized = value.strip()
        if field == "text" and not normalized:
            raise StructuredNoteEditError("Edited note text cannot be empty")
        patch[field] = normalized or None
    return patch


def apply_structured_note_edits(result: dict[str, Any]) -> dict[str, Any]:
    output = _with_stable_item_identity(result)
    generated = output.get("generated") or {}
    effective = copy.deepcopy(generated)
    edits = output.get("user_edits")
    if not isinstance(edits, list):
        edits = []
    output["user_edits"] = copy.deepcopy(edits)
    conflicts: list[dict[str, Any]] = []

    effective_index: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, collection in ITEM_COLLECTIONS.items():
        for item in effective.get(collection) or []:
            if isinstance(item, dict) and item.get("item_id"):
                effective_index[(kind, str(item["item_id"]))] = item

    for edit in edits:
        if not isinstance(edit, dict):
            continue
        kind = str(edit.get("item_kind") or "")
        item_id = str(edit.get("item_id") or "")
        current = _current_item(output, kind, item_id)
        if current is None:
            conflicts.append({
                "item_kind": kind,
                "item_id": item_id,
                "reason": "item_missing",
                "retained_edit": copy.deepcopy(edit),
                "generated": None,
            })
            continue
        if current.get("generated_hash") != edit.get("base_generated_hash"):
            conflicts.append({
                "item_kind": kind,
                "item_id": item_id,
                "reason": "generated_changed",
                "retained_edit": copy.deepcopy(edit),
                "generated": copy.deepcopy(current),
            })
            continue
        target = effective_index.get((kind, item_id))
        if target is None:
            continue
        for field, value in (edit.get("fields") or {}).items():
            if field in EDITABLE_ITEM_FIELDS.get(kind, ()):
                target[field] = value
        target["user_edited"] = True

    output["effective"] = effective
    output["conflicts"] = conflicts
    markdown_source = {**output, "generated": effective}
    output["markdown"] = render_structured_notes_markdown(markdown_source)
    return output


def ensure_editable_structured_notes(
    result: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    if not is_structured_notes_result(result):
        return copy.deepcopy(result)
    output = _with_stable_item_identity(result)
    revision = output.get("revision")
    if not isinstance(revision, dict):
        revision = {"number": 1, "run_id": run_id, "supersedes_run_id": None}
    else:
        revision = copy.deepcopy(revision)
        revision["run_id"] = run_id
        revision.setdefault("number", 1)
        revision.setdefault("supersedes_run_id", None)
    output["revision"] = revision
    return apply_structured_note_edits(output)


def prepare_structured_notes_revision(
    result: dict[str, Any],
    *,
    run_id: str,
    previous_run: dict[str, Any] | None,
) -> dict[str, Any]:
    output = _with_stable_item_identity(result)
    if not is_structured_notes_result(output):
        return output

    previous_result = previous_run.get("result") if isinstance(previous_run, dict) else None
    previous_editable = (
        ensure_editable_structured_notes(previous_result, run_id=str(previous_run.get("id")))
        if isinstance(previous_result, dict) and is_structured_notes_result(previous_result)
        else None
    )
    previous_revision = 0
    if previous_run is not None:
        previous_revision = 1
        if previous_editable:
            revision = previous_editable.get("revision") or {}
            if isinstance(revision.get("number"), int):
                previous_revision = revision["number"]
            output["user_edits"] = copy.deepcopy(previous_editable.get("user_edits") or [])

    output["revision"] = {
        "number": previous_revision + 1,
        "run_id": run_id,
        "supersedes_run_id": previous_run.get("id") if previous_run else None,
    }
    return apply_structured_note_edits(output)


def edit_structured_note_item(
    result: dict[str, Any],
    *,
    run_id: str,
    item_kind: str,
    item_id: str,
    base_generated_hash: str,
    fields: dict[str, Any],
    now: float | None = None,
) -> dict[str, Any]:
    output = ensure_editable_structured_notes(result, run_id=run_id)
    current = _current_item(output, item_kind, item_id)
    if current is None:
        raise StructuredNoteItemNotFound("Structured note item not found")
    if current.get("generated_hash") != base_generated_hash:
        raise StructuredNoteItemChanged("Structured note item changed; reload before saving the edit")
    patch = _normalize_patch(item_kind, fields)
    edits = [
        copy.deepcopy(edit)
        for edit in output.get("user_edits") or []
        if not (
            isinstance(edit, dict)
            and edit.get("item_kind") == item_kind
            and edit.get("item_id") == item_id
        )
    ]
    edits.append({
        "item_kind": item_kind,
        "item_id": item_id,
        "base_generated_hash": current["generated_hash"],
        "base_run_id": run_id,
        "base_generated": copy.deepcopy(current),
        "fields": patch,
        "updated_at": time.time() if now is None else now,
    })
    output["user_edits"] = edits
    return apply_structured_note_edits(output)


def discard_structured_note_edit(
    result: dict[str, Any],
    *,
    run_id: str,
    item_kind: str,
    item_id: str,
) -> dict[str, Any]:
    output = ensure_editable_structured_notes(result, run_id=run_id)
    output["user_edits"] = [
        copy.deepcopy(edit)
        for edit in output.get("user_edits") or []
        if not (
            isinstance(edit, dict)
            and edit.get("item_kind") == item_kind
            and edit.get("item_id") == item_id
        )
    ]
    return apply_structured_note_edits(output)


def effective_generated(result: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    editable = ensure_editable_structured_notes(result, run_id=run_id)
    return copy.deepcopy(editable.get("effective") or editable.get("generated") or {})
