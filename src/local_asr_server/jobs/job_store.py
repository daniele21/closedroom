from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from local_asr_server.catalog import CatalogStore


DEFAULT_JOB_EVENT_CAPACITY = 512
ACTIVE_JOB_STATUSES = (
    "queued",
    "running",
    "waiting_for_service",
    "retrying",
    "cancel_requested",
    "cancelling",
)


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


class JobStore:
    """SQLite-backed store for long-running ClosedRoom jobs and bounded events."""

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        event_capacity: int = DEFAULT_JOB_EVENT_CAPACITY,
    ) -> None:
        if event_capacity < 1:
            raise ValueError("event_capacity must be >= 1")
        self.db_path = db_path or CatalogStore.default_db_path()
        self.event_capacity = event_capacity
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            self._init_db(conn)

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
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                scope_type TEXT,
                scope_id TEXT,
                status TEXT NOT NULL,
                current_step TEXT,
                progress INTEGER NOT NULL DEFAULT 0,
                progress_detail_json TEXT,
                payload_json TEXT,
                result_json TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                dedupe_key TEXT
            );

            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT,
                progress INTEGER NOT NULL,
                message TEXT,
                payload_json TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS job_links (
                parent_job_id TEXT NOT NULL,
                child_job_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                ordinal INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                PRIMARY KEY(parent_job_id, child_job_id),
                FOREIGN KEY(parent_job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(child_job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_scope ON jobs(scope_type, scope_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_type_created ON jobs(type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_job_events_job_sequence ON job_events(job_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_job_links_parent_stage ON job_links(parent_job_id, stage, ordinal);
            CREATE INDEX IF NOT EXISTS idx_job_links_child ON job_links(child_job_id);
            """
        )
        self._ensure_column(conn, "jobs", "progress_detail_json", "TEXT")
        self._ensure_column(conn, "jobs", "dedupe_key", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_dedupe "
            "ON jobs(type, scope_type, scope_id, dedupe_key, created_at DESC)"
        )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection, table: str, column: str, definition: str,
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create(
        self,
        *,
        job_id: str,
        job_type: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        payload: dict[str, Any] | None = None,
        status: str = "queued",
        current_step: str = "queued",
        progress: int = 0,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self.connection() as conn:
            self._insert_job(
                conn,
                job_id=job_id,
                job_type=job_type,
                scope_type=scope_type,
                scope_id=scope_id,
                payload=payload,
                status=status,
                current_step=current_step,
                progress=progress,
                dedupe_key=dedupe_key,
                now=now,
            )
        return self.get(job_id) or {}

    def create_or_get_active(
        self,
        *,
        job_id: str,
        job_type: str,
        scope_type: str,
        scope_id: str,
        dedupe_key: str,
        payload: dict[str, Any] | None = None,
        status: str = "queued",
        current_step: str = "queued",
        progress: int = 0,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically admit one active logical job for the same durable identity."""
        now = time.time()
        placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATUSES)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"""
                SELECT * FROM jobs
                WHERE type = ? AND scope_type = ? AND scope_id = ? AND dedupe_key = ?
                  AND status IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [job_type, scope_type, scope_id, dedupe_key, *ACTIVE_JOB_STATUSES],
            ).fetchone()
            if row is not None:
                return self._row_to_job(row), False
            self._insert_job(
                conn,
                job_id=job_id,
                job_type=job_type,
                scope_type=scope_type,
                scope_id=scope_id,
                payload=payload,
                status=status,
                current_step=current_step,
                progress=progress,
                dedupe_key=dedupe_key,
                now=now,
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row), True

    def _insert_job(
        self,
        conn: sqlite3.Connection,
        *,
        job_id: str,
        job_type: str,
        scope_type: str | None,
        scope_id: str | None,
        payload: dict[str, Any] | None,
        status: str,
        current_step: str,
        progress: int,
        dedupe_key: str | None,
        now: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO jobs (
                id, type, scope_type, scope_id, status, current_step, progress,
                payload_json, created_at, updated_at, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                scope_type,
                scope_id,
                status,
                current_step,
                progress,
                _json_dump(payload),
                now,
                now,
                dedupe_key,
            ),
        )
        self._insert_event(
            conn,
            job_id=job_id,
            status=status,
            current_step=current_step,
            progress=progress,
        )

    def update(
        self,
        job_id: str,
        *,
        status: str,
        current_step: str | None = None,
        progress: int | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        cancel_requested: bool | None = None,
        message: str | None = None,
        event_payload: dict[str, Any] | None = None,
        progress_detail: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get(job_id)
        if existing is None:
            return None
        now = time.time()
        next_step = current_step or status
        next_progress = existing["progress"] if progress is None else progress
        completed_at = now if status in {"completed", "failed", "cancelled", "interrupted"} else existing.get("completed_at")
        started_at = existing.get("started_at")
        if status in {"running", "waiting_for_service", "retrying"} and started_at is None:
            started_at = now
        if cancel_requested is None:
            cancel_requested = bool(existing.get("cancel_requested"))
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    current_step = ?,
                    progress = ?,
                    progress_detail_json = ?,
                    result_json = ?,
                    error = ?,
                    updated_at = ?,
                    started_at = ?,
                    completed_at = ?,
                    cancel_requested = ?
                WHERE id = ?
                """,
                (
                    status,
                    next_step,
                    next_progress,
                    _json_dump(progress_detail),
                    _json_dump(result) if result is not None else _json_dump(existing.get("result")),
                    error if error is not None else existing.get("error"),
                    now,
                    started_at,
                    completed_at,
                    1 if cancel_requested else 0,
                    job_id,
                ),
            )
            self._insert_event(
                conn,
                job_id=job_id,
                status=status,
                current_step=next_step,
                progress=next_progress,
                message=message,
                payload=event_payload,
            )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> dict[str, Any] | None:
        existing = self.get(job_id)
        if existing is None or existing["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return existing
        return self.update(job_id, status="cancelling", current_step="cancelling", cancel_requested=True)

    def interrupt_incomplete(self, *, reason: str = "Interrupted by server restart") -> list[dict[str, Any]]:
        """Terminally mark work that cannot survive this process restart."""
        interrupted = []
        for job in self.list_jobs(limit=500):
            if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                continue
            updated = self.update(job["id"], status="interrupted", current_step="interrupted", error=reason, message=reason)
            if updated:
                interrupted.append(updated)
        return interrupted

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def find_latest(
        self,
        *,
        job_type: str,
        scope_type: str,
        scope_id: str,
        dedupe_key: str | None = None,
        statuses: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["type = ?", "scope_type = ?", "scope_id = ?"]
        params: list[Any] = [job_type, scope_type, scope_id]
        if dedupe_key is not None:
            clauses.append("dedupe_key = ?")
            params.append(dedupe_key)
        status_values = list(statuses or [])
        if status_values:
            placeholders = ", ".join("?" for _ in status_values)
            clauses.append(f"status IN ({placeholders})")
            params.extend(status_values)
        with self.connection() as conn:
            row = conn.execute(
                f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 1",
                params,
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(
        self,
        *,
        job_type: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if job_type:
            clauses.append("type = ?")
            params.append(job_type)
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_id:
            clauses.append("scope_id = ?")
            params.append(scope_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def link_child(
        self,
        parent_job_id: str,
        child_job_id: str,
        *,
        stage: str,
        ordinal: int = 0,
    ) -> None:
        """Persist a lightweight orchestration relationship without owning execution."""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO job_links (parent_job_id, child_job_id, stage, ordinal, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(parent_job_id, child_job_id) DO UPDATE SET
                    stage = excluded.stage,
                    ordinal = excluded.ordinal
                """,
                (parent_job_id, child_job_id, stage, ordinal, time.time()),
            )

    def list_children(
        self,
        parent_job_id: str,
        *,
        stage: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [parent_job_id]
        stage_clause = ""
        if stage is not None:
            stage_clause = " AND links.stage = ?"
            params.append(stage)
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT jobs.*, links.stage AS link_stage, links.ordinal AS link_ordinal
                FROM job_links AS links
                JOIN jobs ON jobs.id = links.child_job_id
                WHERE links.parent_job_id = ?{stage_clause}
                ORDER BY links.ordinal ASC, links.created_at ASC
                """,
                params,
            ).fetchall()
        items = []
        for row in rows:
            item = self._row_to_job(row)
            item["link_stage"] = row["link_stage"]
            item["link_ordinal"] = row["link_ordinal"]
            items.append(item)
        return items

    def events_after(self, job_id: str, sequence: int = 0) -> list[dict[str, Any]] | None:
        if self.get(job_id) is None:
            return None
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (job_id, sequence),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        *,
        job_id: str,
        status: str,
        current_step: str | None,
        progress: int,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM job_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        next_sequence = int(row["next_sequence"])
        conn.execute(
            """
            INSERT INTO job_events (
                job_id, sequence, status, current_step, progress, message, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                next_sequence,
                status,
                current_step,
                progress,
                message,
                _json_dump(payload),
                time.time(),
            ),
        )
        conn.execute(
            "DELETE FROM job_events WHERE job_id = ? AND sequence <= ?",
            (job_id, next_sequence - self.event_capacity),
        )

    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "scope_type": row["scope_type"],
            "scope_id": row["scope_id"],
            "status": row["status"],
            "current_step": row["current_step"],
            "progress": row["progress"],
            "progress_detail": _json_load(row["progress_detail_json"], None),
            "payload": _json_load(row["payload_json"], None),
            "result": _json_load(row["result_json"], None),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "cancel_requested": bool(row["cancel_requested"]),
            "dedupe_key": row["dedupe_key"],
        }

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "sequence": row["sequence"],
            "status": row["status"],
            "current_step": row["current_step"],
            "progress": row["progress"],
            "message": row["message"],
            "payload": _json_load(row["payload_json"], None),
            "created_at": row["created_at"],
        }
