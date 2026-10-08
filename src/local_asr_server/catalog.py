from __future__ import annotations

import contextlib
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from local_asr_server.paths import get_app_support_dir
from local_asr_server.settings import load_settings


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _nullable_bool(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _nullable_int_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


class CatalogStore:
    """Central SQLite catalog for queryable ClosedRoom metadata."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self.default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            self._init_db(conn)

    @staticmethod
    def default_db_path() -> Path:
        settings = load_settings()
        transcriptions_dir = Path(settings["transcriptions_dir"]).expanduser().resolve()
        recordings_dir = Path(settings["recordings_dir"]).expanduser().resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if temp_root in transcriptions_dir.parents or temp_root in recordings_dir.parents:
            transcriptions_dir.mkdir(parents=True, exist_ok=True)
            return transcriptions_dir / "closedroom.db"
        return get_app_support_dir() / "closedroom.db"

    @contextlib.contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                project_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                stopped_at TEXT,
                completed_at TEXT,
                mime_type TEXT,
                extension TEXT,
                chunk_count INTEGER DEFAULT 0,
                bytes_written INTEGER DEFAULT 0,
                model TEXT,
                language TEXT,
                error TEXT,
                relative_dir TEXT,
                audio_file TEXT,
                capture_mode TEXT,
                primary_track_id TEXT,
                audio_tracks TEXT,
                capture_backend TEXT,
                capture_status TEXT,
                quality_report TEXT,
                warnings TEXT,
                visual_intelligence TEXT,
                archived_at TEXT
            );

            CREATE TABLE IF NOT EXISTS transcriptions (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                audio_filename TEXT,
                recording_id TEXT,
                model TEXT,
                language TEXT,
                text TEXT,
                segments TEXT,
                stats TEXT,
                analysis TEXT,
                merged_sources TEXT,
                source_tracks TEXT,
                asr_provider TEXT,
                backend TEXT,
                provider_options TEXT,
                hidden INTEGER DEFAULT 0,
                merged_into TEXT,
                file_name TEXT
            );

            CREATE TABLE IF NOT EXISTS analysis_runs (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                transcription_id TEXT,
                recording_id TEXT,
                analysis_type TEXT NOT NULL DEFAULT 'meeting_brief',
                template_id TEXT,
                template_version TEXT,
                pipeline_run_id TEXT,
                provider TEXT NOT NULL,
                model TEXT,
                temperature REAL,
                reasoning TEXT NOT NULL DEFAULT 'auto',
                effective_reasoning INTEGER,
                show_thinking INTEGER NOT NULL DEFAULT 0,
                max_output_tokens INTEGER,
                json_mode INTEGER NOT NULL DEFAULT 1,
                llm_options_json TEXT,
                prompt_version TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                result_markdown TEXT,
                source_ids_json TEXT,
                period_start TEXT,
                period_end TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                completed_at REAL
            );

            CREATE TABLE IF NOT EXISTS analysis_cache (
                cache_key TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_recordings_created_at ON recordings(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_recordings_project ON recordings(project_name);
            CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);
            CREATE INDEX IF NOT EXISTS idx_transcriptions_recording_id ON transcriptions(recording_id);
            CREATE INDEX IF NOT EXISTS idx_transcriptions_audio_filename ON transcriptions(audio_filename);
            CREATE INDEX IF NOT EXISTS idx_transcriptions_visible ON transcriptions(hidden, merged_into, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_transcriptions_timestamp ON transcriptions(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_scope ON analysis_runs(scope_type, scope_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_transcription ON analysis_runs(transcription_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_input_hash ON analysis_runs(input_hash);
            CREATE INDEX IF NOT EXISTS idx_analysis_cache_created_at ON analysis_cache(created_at DESC);
            """
        )
        self._ensure_column(conn, "recordings", "capture_mode", "TEXT")
        self._ensure_column(conn, "recordings", "primary_track_id", "TEXT")
        self._ensure_column(conn, "recordings", "audio_tracks", "TEXT")
        self._ensure_column(conn, "recordings", "capture_backend", "TEXT")
        self._ensure_column(conn, "recordings", "capture_status", "TEXT")
        self._ensure_column(conn, "recordings", "quality_report", "TEXT")
        self._ensure_column(conn, "recordings", "warnings", "TEXT")
        self._ensure_column(conn, "recordings", "visual_intelligence", "TEXT")
        self._ensure_column(conn, "recordings", "archived_at", "TEXT")
        self._ensure_column(conn, "transcriptions", "source_tracks", "TEXT")
        self._ensure_column(conn, "transcriptions", "asr_provider", "TEXT")
        self._ensure_column(conn, "transcriptions", "backend", "TEXT")
        self._ensure_column(conn, "transcriptions", "provider_options", "TEXT")
        self._ensure_column(conn, "analysis_runs", "analysis_type", "TEXT NOT NULL DEFAULT 'meeting_brief'")
        self._ensure_column(conn, "analysis_runs", "template_id", "TEXT")
        self._ensure_column(conn, "analysis_runs", "template_version", "TEXT")
        self._ensure_column(conn, "analysis_runs", "pipeline_run_id", "TEXT")
        self._ensure_column(conn, "analysis_runs", "result_markdown", "TEXT")
        self._ensure_column(conn, "analysis_runs", "source_ids_json", "TEXT")
        self._ensure_column(conn, "analysis_runs", "period_start", "TEXT")
        self._ensure_column(conn, "analysis_runs", "period_end", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_runs_type ON analysis_runs(analysis_type, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_runs_pipeline ON analysis_runs(pipeline_run_id)")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {row["name"] for row in rows}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def upsert_recording(self, metadata: dict[str, Any], audio_file: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO recordings (
                    id, title, project_name, status, created_at, stopped_at, completed_at,
                    mime_type, extension, chunk_count, bytes_written, model, language, error,
                    relative_dir, audio_file, capture_mode, primary_track_id, audio_tracks,
                    capture_backend, capture_status, quality_report, warnings, visual_intelligence, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    project_name = excluded.project_name,
                    status = excluded.status,
                    stopped_at = excluded.stopped_at,
                    completed_at = excluded.completed_at,
                    mime_type = excluded.mime_type,
                    extension = excluded.extension,
                    chunk_count = excluded.chunk_count,
                    bytes_written = excluded.bytes_written,
                    model = excluded.model,
                    language = excluded.language,
                    error = excluded.error,
                    relative_dir = excluded.relative_dir,
                    audio_file = excluded.audio_file,
                    capture_mode = excluded.capture_mode,
                    primary_track_id = excluded.primary_track_id,
                    audio_tracks = excluded.audio_tracks,
                    capture_backend = excluded.capture_backend,
                    capture_status = excluded.capture_status,
                    quality_report = excluded.quality_report,
                    warnings = excluded.warnings,
                    visual_intelligence = excluded.visual_intelligence,
                    archived_at = excluded.archived_at
                """,
                (
                    metadata["id"],
                    metadata.get("title") or "",
                    metadata.get("project_name") or "",
                    metadata.get("status") or "",
                    metadata.get("created_at") or "",
                    metadata.get("stopped_at"),
                    metadata.get("completed_at"),
                    metadata.get("mime_type"),
                    metadata.get("extension"),
                    metadata.get("chunk_count") or 0,
                    metadata.get("bytes_written") or 0,
                    metadata.get("model"),
                    metadata.get("language"),
                    metadata.get("error"),
                    metadata.get("relative_dir"),
                    audio_file,
                    metadata.get("capture_mode"),
                    metadata.get("primary_track_id"),
                    _json_dump(metadata.get("audio_tracks", [])),
                    metadata.get("capture_backend"),
                    metadata.get("capture_status"),
                    _json_dump(metadata.get("quality_report")),
                    _json_dump(metadata.get("warnings", [])),
                    _json_dump(metadata.get("visual_intelligence")),
                    metadata.get("archived_at"),
                ),
            )

    def delete_recording(self, recording_id: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))

    def upsert_transcription(self, data: dict[str, Any], file_name: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO transcriptions (
                    id, timestamp, audio_filename, recording_id, model, language, text,
                    segments, stats, analysis, merged_sources, source_tracks,
                    asr_provider, backend, provider_options, hidden, merged_into, file_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    audio_filename = excluded.audio_filename,
                    recording_id = excluded.recording_id,
                    model = excluded.model,
                    language = excluded.language,
                    text = excluded.text,
                    segments = excluded.segments,
                    stats = excluded.stats,
                    analysis = excluded.analysis,
                    merged_sources = excluded.merged_sources,
                    source_tracks = excluded.source_tracks,
                    asr_provider = excluded.asr_provider,
                    backend = excluded.backend,
                    provider_options = excluded.provider_options,
                    hidden = excluded.hidden,
                    merged_into = excluded.merged_into,
                    file_name = excluded.file_name
                """,
                (
                    data["id"],
                    data.get("timestamp") or "",
                    data.get("audio_filename"),
                    data.get("recording_id") or "",
                    data.get("model"),
                    data.get("language"),
                    data.get("text") or "",
                    _json_dump(data.get("segments", [])),
                    _json_dump(data.get("stats", {})),
                    _json_dump(data.get("analysis")) if data.get("analysis") is not None else None,
                    _json_dump(data.get("merged_sources")) if data.get("merged_sources") is not None else None,
                    _json_dump(data.get("source_tracks")) if data.get("source_tracks") is not None else None,
                    data.get("asr_provider") or data.get("stats", {}).get("asr_provider"),
                    data.get("backend") or data.get("stats", {}).get("backend"),
                    _json_dump(data.get("provider_options") or data.get("stats", {}).get("provider_options") or {}),
                    1 if data.get("hidden") else 0,
                    data.get("merged_into"),
                    file_name or data.get("file_name"),
                ),
            )

    def row_to_transcription(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "audio_filename": row["audio_filename"],
            "recording_id": row["recording_id"],
            "model": row["model"],
            "language": row["language"],
            "text": row["text"],
            "segments": _json_load(row["segments"], []),
            "stats": _json_load(row["stats"], {}),
            "analysis": _json_load(row["analysis"], None),
            "merged_sources": _json_load(row["merged_sources"], None),
            "source_tracks": _json_load(row["source_tracks"], None),
            "asr_provider": row["asr_provider"],
            "backend": row["backend"],
            "provider_options": _json_load(row["provider_options"], {}),
            "hidden": bool(row["hidden"]),
            "merged_into": row["merged_into"],
        }

    def update_transcription_flags(self, transcription_id: str, *, hidden: bool, merged_into: str | None) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE transcriptions SET hidden = ?, merged_into = ? WHERE id = ?",
                (1 if hidden else 0, merged_into, transcription_id),
            )

    def update_analysis(self, transcription_id: str, analysis: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE transcriptions SET analysis = ? WHERE id = ?",
                (_json_dump(analysis), transcription_id),
            )

    def get_analysis_cache(self, cache_key: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT result_json FROM analysis_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return _json_load(row["result_json"], None) if row else None

    def save_analysis_cache(self, cache_key: str, result: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO analysis_cache (cache_key, result_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    result_json = excluded.result_json,
                    created_at = excluded.created_at
                """,
                (cache_key, _json_dump(result), time.time()),
            )

    def create_analysis_run(self, run: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO analysis_runs (
                    id, job_id, scope_type, scope_id, transcription_id, recording_id,
                    analysis_type, template_id, template_version, pipeline_run_id,
                    provider, model, temperature, reasoning, effective_reasoning,
                    show_thinking, max_output_tokens, json_mode, llm_options_json,
                    prompt_version, input_hash, status, result_json, result_markdown,
                    source_ids_json, period_start, period_end, error,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["id"],
                    run.get("job_id"),
                    run["scope_type"],
                    run["scope_id"],
                    run.get("transcription_id"),
                    run.get("recording_id"),
                    run.get("analysis_type") or "meeting_brief",
                    run.get("template_id"),
                    run.get("template_version"),
                    run.get("pipeline_run_id"),
                    run["provider"],
                    run.get("model"),
                    run.get("temperature"),
                    run.get("reasoning") or "auto",
                    _nullable_bool(run.get("effective_reasoning")),
                    1 if run.get("show_thinking") else 0,
                    run.get("max_output_tokens"),
                    1 if run.get("json_mode", True) else 0,
                    _json_dump(run.get("llm_options")),
                    run.get("prompt_version") or "summary_v1",
                    run["input_hash"],
                    run.get("status") or "queued",
                    _json_dump(run.get("result")) if run.get("result") is not None else None,
                    run.get("result_markdown"),
                    _json_dump(run.get("source_ids")) if run.get("source_ids") is not None else None,
                    run.get("period_start"),
                    run.get("period_end"),
                    run.get("error"),
                    run["created_at"],
                    run.get("completed_at"),
                ),
            )
        stored = self.get_analysis_run(run["id"])
        return stored or {}

    def update_analysis_run(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        completed_at: float | None = None,
    ) -> dict[str, Any] | None:
        with self.connection() as conn:
            existing = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
            if existing is None:
                return None
            conn.execute(
                """
                UPDATE analysis_runs
                SET status = ?, result_json = ?, result_markdown = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    _json_dump(result) if result is not None else existing["result_json"],
                    result.get("markdown") if isinstance(result, dict) and result.get("markdown") is not None else existing["result_markdown"],
                    error if error is not None else existing["error"],
                    completed_at if completed_at is not None else existing["completed_at"],
                    run_id,
                ),
            )
        return self.get_analysis_run(run_id)

    def interrupt_analysis_runs_for_jobs(self, job_ids: list[str], *, reason: str) -> None:
        if not job_ids:
            return
        placeholders = ", ".join("?" for _ in job_ids)
        with self.connection() as conn:
            conn.execute(
                f"""
                UPDATE analysis_runs
                SET status = 'interrupted', error = ?, completed_at = ?
                WHERE job_id IN ({placeholders}) AND status NOT IN ('completed', 'failed', 'cancelled', 'interrupted')
                """,
                [reason, time.time(), *job_ids],
            )

    def get_analysis_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_analysis_run(row) if row else None

    def list_analysis_runs(
        self,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        transcription_id: str | None = None,
        recording_id: str | None = None,
        analysis_type: str | None = None,
        pipeline_run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_id:
            clauses.append("scope_id = ?")
            params.append(scope_id)
        if transcription_id:
            clauses.append("transcription_id = ?")
            params.append(transcription_id)
        if recording_id:
            clauses.append("recording_id = ?")
            params.append(recording_id)
        if analysis_type:
            clauses.append("analysis_type = ?")
            params.append(analysis_type)
        if pipeline_run_id:
            clauses.append("pipeline_run_id = ?")
            params.append(pipeline_run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM analysis_runs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_analysis_run(row) for row in rows]

    def _row_to_analysis_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "scope_type": row["scope_type"],
            "scope_id": row["scope_id"],
            "transcription_id": row["transcription_id"],
            "recording_id": row["recording_id"],
            "analysis_type": row["analysis_type"],
            "template_id": row["template_id"],
            "template_version": row["template_version"],
            "pipeline_run_id": row["pipeline_run_id"],
            "provider": row["provider"],
            "model": row["model"],
            "temperature": row["temperature"],
            "reasoning": row["reasoning"],
            "effective_reasoning": _nullable_int_bool(row["effective_reasoning"]),
            "show_thinking": bool(row["show_thinking"]),
            "max_output_tokens": row["max_output_tokens"],
            "json_mode": bool(row["json_mode"]),
            "llm_options": _json_load(row["llm_options_json"], {}),
            "prompt_version": row["prompt_version"],
            "input_hash": row["input_hash"],
            "status": row["status"],
            "result": _json_load(row["result_json"], None),
            "result_markdown": row["result_markdown"],
            "source_ids": _json_load(row["source_ids_json"], []),
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "error": row["error"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    def delete_transcription(self, transcription_id: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM transcriptions WHERE id = ?", (transcription_id,))

    def import_transcriptions_dir(self, root: Path) -> None:
        with self.connection() as conn:
            rows = conn.execute("SELECT id, file_name FROM transcriptions").fetchall()
            db_ids = {row["id"] for row in rows}
            db_files = {row["file_name"] for row in rows if row["file_name"]}
        for path in root.glob("transcript_*.json"):
            if path.name in db_files:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("id") and data["id"] not in db_ids:
                self.upsert_transcription(data, file_name=path.name)

    def list_transcriptions(self, page: int = 1, limit: int = 10) -> tuple[list[dict[str, Any]], int]:
        offset = max(0, page - 1) * limit
        with self.connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE hidden = 0 AND merged_into IS NULL"
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT * FROM transcriptions
                WHERE hidden = 0 AND merged_into IS NULL
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self.row_to_transcription(row) for row in rows], total

    def get_transcription(self, transcription_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM transcriptions WHERE id = ?", (transcription_id,)).fetchone()
        return self.row_to_transcription(row) if row else None

    def find_transcription_for_recording(self, recording_id: str, audio_filename: str = "") -> dict[str, Any] | None:
        with self.connection() as conn:
            row = None
            if recording_id:
                row = conn.execute(
                    "SELECT * FROM transcriptions WHERE recording_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (recording_id,),
                ).fetchone()
            elif audio_filename:
                row = conn.execute(
                    "SELECT * FROM transcriptions WHERE audio_filename = ? ORDER BY timestamp DESC LIMIT 1",
                    (audio_filename,),
                ).fetchone()
        if row is None:
            return None
        item = self.row_to_transcription(row)
        if item.get("merged_into"):
            return self.get_transcription(item["merged_into"]) or item
        return item

    def stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            recordings_count = conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
            transcriptions_count = conn.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE hidden = 0 AND merged_into IS NULL"
            ).fetchone()[0]
            latest_recording = conn.execute("SELECT * FROM recordings ORDER BY created_at DESC LIMIT 1").fetchone()
            latest_transcription = conn.execute(
                "SELECT * FROM transcriptions WHERE hidden = 0 AND merged_into IS NULL ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        return {
            "recordings_count": recordings_count,
            "transcriptions_count": transcriptions_count,
            "latest_recording": self.row_to_recording(latest_recording) if latest_recording else None,
            "latest_transcription": self.row_to_transcription(latest_transcription) if latest_transcription else None,
        }

    def row_to_recording(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["audio_tracks"] = _json_load(item.get("audio_tracks"), [])
        item["visual_intelligence"] = _json_load(item.get("visual_intelligence"), None)
        item["quality_report"] = _json_load(item.get("quality_report"), None)
        item["warnings"] = _json_load(item.get("warnings"), [])
        return item
