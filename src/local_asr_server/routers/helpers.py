from __future__ import annotations

from local_asr_server.app_services import get_services

import os
from typing import Any, TYPE_CHECKING

from local_asr_server.transcription_quality import dedupe_cross_track_segments
from local_asr_server.asr_models import get_asr_backend
from local_asr_server.asr_provider import ASR_PROVIDER_LOCAL, public_asr_metadata
from local_asr_server.speaker_labels import apply_speaker_labels
from local_asr_server.structured_notes_projection import expand_analysis_runs

if TYPE_CHECKING:
    from fastapi import FastAPI


def _format_time_label(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes = total // 60
    secs = total % 60
    return f"{minutes:02d}:{secs:02d}"


def _merge_track_transcriptions(
    track_results: list[dict],
    *,
    model: str,
    language: str | None,
    elapsed: float,
    recording_id: str,
    asr_provider: str | None = None,
    backend: str | None = None,
    provider_options: dict[str, Any] | None = None,
) -> dict:
    segments = []
    source_tracks = []
    text_lines = []
    next_id = 0
    languages: list[str] = []

    for item in track_results:
        track = item["track"]
        result = item["result"]
        source_track = {
            "id": track["id"],
            "source": track.get("source"),
            "label": track.get("label"),
            "audio_file": track.get("audio_file"),
        }
        if result.get("metadata"):
            source_track["transcription_metadata"] = result["metadata"]
        if result.get("provider"):
            source_track["asr_provider"] = result["provider"]
        if result.get("backend"):
            source_track["backend"] = result["backend"]
        if "raw_text" in result:
            source_track["raw_text"] = result["raw_text"]
        if "raw_segments" in result:
            source_track["raw_segments"] = result["raw_segments"]
        source_tracks.append(source_track)
        if result.get("language") and result["language"] not in languages:
            languages.append(result["language"])
        for seg in result.get("segments", []) or []:
            merged_seg = dict(seg)
            merged_seg["id"] = next_id
            next_id += 1
            merged_seg["track_id"] = track["id"]
            merged_seg["source"] = track.get("source")
            merged_seg["speaker_label"] = track.get("label")
            segments.append(merged_seg)

    segments = dedupe_cross_track_segments(segments)
    segments.sort(key=lambda seg: (seg.get("start") or 0.0, seg.get("end") or 0.0, seg.get("track_id") or ""))
    for index, seg in enumerate(segments):
        seg["id"] = index
        label = seg.get("speaker_label") or seg.get("source") or "Audio"
        text = (seg.get("text") or "").strip()
        if text:
            text_lines.append(f"[{_format_time_label(float(seg.get('start') or 0.0))}] {label}: {text}")

    resolved_provider = asr_provider or next((item["result"].get("asr_provider") or item["result"].get("provider") for item in track_results if item["result"].get("asr_provider") or item["result"].get("provider")), None) or ASR_PROVIDER_LOCAL
    resolved_model = next((item["result"].get("model") for item in track_results if item["result"].get("model")), None) or model
    asr_metadata = public_asr_metadata(resolved_provider, resolved_model, provider_options or {})
    if backend:
        asr_metadata["backend"] = backend

    return apply_speaker_labels({
        "text": "\n".join(text_lines),
        "language": ", ".join(languages) if languages else (language or "it"),
        "segments": segments,
        "source_tracks": source_tracks,
        "model": asr_metadata["model"],
        "backend": asr_metadata["backend"] or next((item["result"].get("backend") for item in track_results if item["result"].get("backend")), None) or get_asr_backend(model),
        "asr_provider": asr_metadata["asr_provider"],
        "provider_options": asr_metadata["provider_options"],
        "recording_id": recording_id,
        "stats": {
            "time_total_seconds": elapsed,
            "track_count": len(track_results),
            "cross_track_deduplication_enabled": True,
            **asr_metadata,
        },
    })


def _current_analysis_runs(
    runs: list[dict[str, Any]],
    transcription: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Keep derived Meeting state tied to the currently selected transcript."""
    if transcription is None:
        return [run for run in runs if not run.get("transcription_id")]
    transcription_id = transcription.get("id")
    return [run for run in runs if run.get("transcription_id") == transcription_id]


def _exclude_incomplete_preparation_runs(
    runs: list[dict[str, Any]],
    preparation_jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Do not promote partial/cancelled preparation output as ready Meeting notes."""
    incomplete_pipeline_ids = {
        (job.get("result") or {}).get("pipeline_run_id")
        for job in preparation_jobs
        if job.get("type") == "meeting_preparation"
        and job.get("status") in {"failed", "interrupted", "cancelled"}
        and (job.get("result") or {}).get("pipeline_run_id")
    }
    if not incomplete_pipeline_ids:
        return runs
    return [
        run for run in runs
        if run.get("pipeline_run_id") not in incomplete_pipeline_ids
    ]


def _build_projects(app: FastAPI) -> dict:
    recordings = get_services(app).recordings.list(limit=999)
    projects: dict[str, dict] = {}
    unassigned_name = "Senza progetto"
    for recording in recordings:
        project_name = (recording.get("project_name") or "").strip() or unassigned_name
        bucket = projects.setdefault(project_name, {
            "name": project_name,
            "is_unassigned": project_name == unassigned_name,
            "items": [],
        })
        transcription = get_services(app).transcriptions.find_for_recording(recording["id"])
        runs = get_services(app).catalog.list_analysis_runs(recording_id=recording["id"], limit=50)
        if transcription:
            transcription_runs = get_services(app).catalog.list_analysis_runs(transcription_id=transcription["id"], limit=50)
            existing = {run["id"] for run in runs}
            runs.extend(run for run in transcription_runs if run["id"] not in existing)
        current_runs = _current_analysis_runs(runs, transcription)
        preparation_jobs = get_services(app).transcription_jobs.list(
            job_type="meeting_preparation",
            scope_type="recording",
            scope_id=recording["id"],
            limit=50,
        )
        canonical_runs = expand_analysis_runs(
            _exclude_incomplete_preparation_runs(current_runs, preparation_jobs)
        )
        latest_analysis = next((run for run in sorted(canonical_runs, key=lambda item: item.get("created_at") or 0, reverse=True) if run.get("status") == "completed"), None)
        legacy_analysis = (
            transcription.get("analysis")
            if transcription and not preparation_jobs
            else None
        )
        bucket["items"].append({
            "recording": recording,
            "transcription": transcription,
            "analysis": latest_analysis or legacy_analysis,
            "analysis_runs": sorted(expand_analysis_runs(runs), key=lambda item: item.get("created_at") or 0, reverse=True),
        })
    items = sorted(projects.values(), key=lambda item: (item["is_unassigned"], item["name"].lower()))
    return {"items": items}


def _meeting_status(recording: dict[str, Any], transcription: dict[str, Any] | None, runs: list[dict[str, Any]]) -> str:
    active_statuses = {"queued", "running", "waiting_for_service", "retrying"}
    if any(run.get("status") in active_statuses for run in runs):
        return "analyzing"
    if any(run.get("status") == "completed" for run in runs):
        return "ready"
    if transcription:
        return "transcribed"
    if recording.get("status") in {"recording", "finalizing"}:
        return "recording"
    return "recorded"


def _compact_recording(recording: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: value
        for key, value in recording.items()
        if key not in {"timeline", "quality_report", "warnings"}
    }
    tracks = []
    for track in compact.get("audio_tracks") or []:
        tracks.append({key: value for key, value in track.items() if key != "chunks"})
    compact["audio_tracks"] = tracks
    return compact


def _compact_transcription(transcription: dict[str, Any] | None) -> dict[str, Any] | None:
    if not transcription:
        return None
    compact = {
        key: value
        for key, value in transcription.items()
        if key not in {"segments", "source_tracks", "merged_sources"}
    }
    text = compact.get("text") or ""
    compact["text"] = text[:1000]
    compact["text_preview"] = text[:240]
    compact["text_truncated"] = len(text) > 1000
    return compact


def _detail_transcription(transcription: dict[str, Any] | None) -> dict[str, Any] | None:
    if not transcription:
        return None
    return {
        key: value
        for key, value in transcription.items()
        if key not in {"segments", "source_tracks", "merged_sources"}
    }


def _compact_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"payload", "result"}
    }


def _compact_analysis_run(run: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: value
        for key, value in run.items()
        if key not in {"result", "llm_options"}
    }
    if compact.get("result_markdown"):
        compact["result_markdown"] = compact["result_markdown"][:1000]
        compact["result_truncated"] = True
    return compact


def _build_meeting(app: FastAPI, recording: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    transcription = get_services(app).transcriptions.find_for_recording(recording["id"])
    runs = get_services(app).catalog.list_analysis_runs(recording_id=recording["id"], limit=200)
    if transcription:
        transcription_runs = get_services(app).catalog.list_analysis_runs(
            transcription_id=transcription["id"],
            limit=200,
        )
        existing = {run["id"] for run in runs}
        runs.extend(run for run in transcription_runs if run["id"] not in existing)
    current_runs = _current_analysis_runs(runs, transcription)
    related_jobs = get_services(app).transcription_jobs.list(
        scope_type="recording",
        scope_id=recording["id"],
        limit=50,
    )
    if transcription:
        related_jobs.extend(
            get_services(app).transcription_jobs.list(
                scope_type="transcription",
                scope_id=transcription["id"],
                limit=50,
            )
        )
    canonical_runs = _exclude_incomplete_preparation_runs(current_runs, related_jobs)
    expanded_canonical_runs = expand_analysis_runs(canonical_runs)
    jobs = [
        _compact_job(job)
        for job in sorted(
            {job["id"]: job for job in related_jobs}.values(),
            key=lambda item: item.get("created_at") or 0,
            reverse=True,
        )
    ]
    latest_by_type: dict[str, dict[str, Any]] = {}
    for run in sorted(expanded_canonical_runs, key=lambda item: item.get("created_at") or 0, reverse=True):
        analysis_type = run.get("analysis_type") or "meeting_brief"
        if analysis_type not in latest_by_type and run.get("status") == "completed":
            latest_by_type[analysis_type] = run
    public_runs = sorted(expand_analysis_runs(runs), key=lambda item: item.get("created_at") or 0, reverse=True)
    public_latest = latest_by_type
    if compact:
        public_runs = [_compact_analysis_run(run) for run in public_runs]
        public_latest = {analysis_type: _compact_analysis_run(run) for analysis_type, run in latest_by_type.items()}
    return {
        "id": recording["id"],
        "recording": _compact_recording(recording),
        "transcription": _compact_transcription(transcription) if compact else _detail_transcription(transcription),
        "analysis_runs": public_runs,
        "latest_analysis": public_latest,
        "jobs": jobs,
        "status": _meeting_status(recording, transcription, canonical_runs),
        "project_name": recording.get("project_name") or "",
        "created_at": recording.get("created_at"),
        "updated_at": recording.get("completed_at") or recording.get("stopped_at") or recording.get("created_at"),
    }


def _build_meetings(app: FastAPI, limit: int = 50) -> dict[str, Any]:
    recordings = get_services(app).recordings.list(limit=max(1, min(limit, 200)))
    return {"items": [_build_meeting(app, recording, compact=True) for recording in recordings]}


FALSE_ENV_VALUES = {"0", "false", "no", "off"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in FALSE_ENV_VALUES


def _parse_allowed_origins(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _extract_bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token
