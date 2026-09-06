from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from local_asr_server.catalog import CatalogStore


SEARCH_SCHEMA_VERSION = "2"
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_TRIGGER_NAMES = (
    "meeting_search_recording_insert",
    "meeting_search_recording_update",
    "meeting_search_recording_delete",
    "meeting_search_transcription_insert",
    "meeting_search_transcription_update",
    "meeting_search_transcription_delete",
    "meeting_search_analysis_insert",
    "meeting_search_analysis_update",
    "meeting_search_analysis_delete",
)


class MeetingSearchUnavailable(RuntimeError):
    """Raised when the bundled SQLite runtime cannot provide FTS5 search."""


@dataclass(frozen=True)
class MeetingSearchPage:
    recording_ids: list[str]
    total: int
    page: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.page * self.limit < self.total


class CatalogMeetingSearch:
    """Bounded meeting search projected from the canonical CatalogStore tables.

    The FTS index lives in the same SQLite database as CatalogStore. SQLite triggers
    only mark affected recording ids dirty; the projection is refreshed transactionally
    before a search. This keeps canonical persistence ownership in CatalogStore while
    avoiding whole-archive extraction in the frontend.
    """

    def __init__(self, catalog: CatalogStore) -> None:
        self.catalog = catalog

    def search(
        self,
        *,
        query: str = "",
        page: int = 1,
        limit: int = 25,
        project_name: str | None = None,
    ) -> MeetingSearchPage:
        page = max(1, int(page))
        limit = max(1, min(int(limit), 50))
        project = (project_name or "").strip()
        terms = self._query_terms(query)
        offset = (page - 1) * limit

        with self.catalog.connection() as conn:
            self._ensure_schema(conn)
            self._refresh_dirty(conn)

            if terms:
                match = " AND ".join(f'"{term}"*' for term in terms)
                project_clause = "AND recordings.project_name = ?" if project else ""
                params: list[Any] = [match]
                if project:
                    params.append(project)
                total = int(
                    conn.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM meeting_search_fts
                        JOIN recordings ON recordings.id = meeting_search_fts.recording_id
                        WHERE meeting_search_fts MATCH ? {project_clause}
                        """,
                        params,
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    f"""
                    SELECT meeting_search_fts.recording_id
                    FROM meeting_search_fts
                    JOIN recordings ON recordings.id = meeting_search_fts.recording_id
                    WHERE meeting_search_fts MATCH ? {project_clause}
                    ORDER BY bm25(meeting_search_fts), meeting_search_fts.created_at DESC,
                             meeting_search_fts.recording_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    [*params, limit, offset],
                ).fetchall()
            else:
                project_clause = "WHERE project_name = ?" if project else ""
                params = [project] if project else []
                total = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM recordings {project_clause}",
                        params,
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    f"""
                    SELECT id AS recording_id
                    FROM recordings
                    {project_clause}
                    ORDER BY created_at DESC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    [*params, limit, offset],
                ).fetchall()

        return MeetingSearchPage(
            recording_ids=[str(row["recording_id"]) for row in rows],
            total=total,
            page=page,
            limit=limit,
        )

    def assert_available(self) -> None:
        """Initialize/probe FTS5; used by packaged-app validation as well as search."""
        with self.catalog.connection() as conn:
            self._ensure_schema(conn)
            self._refresh_dirty(conn)

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        # Treat user input as text, not raw FTS syntax. Limiting both term count and
        # length keeps query cost predictable and prevents malformed MATCH clauses.
        return [token[:64] for token in _TOKEN_RE.findall(query.casefold())[:12] if token]

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS meeting_search_fts USING "
                "fts5(recording_id UNINDEXED, title, project_name, transcript_text, "
                "notes_text, created_at UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
            )
        except sqlite3.OperationalError as exc:
            raise MeetingSearchUnavailable(
                "This ClosedRoom build does not provide the required SQLite FTS5 support"
            ) from exc

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meeting_search_dirty (
                recording_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS meeting_search_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        current = conn.execute(
            "SELECT value FROM meeting_search_meta WHERE key = 'schema_version'"
        ).fetchone()
        schema_changed = current is None or str(current["value"]) != SEARCH_SCHEMA_VERSION
        if schema_changed:
            for trigger_name in _TRIGGER_NAMES:
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")

        # Use an explicit UPSERT conflict clause rather than INSERT OR IGNORE. The
        # latter can inherit the conflict policy of the outer CatalogStore UPSERT when
        # executed from a trigger, turning an idempotent dirty mark into a UNIQUE error.
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS meeting_search_recording_insert
            AFTER INSERT ON recordings BEGIN
                INSERT INTO meeting_search_dirty(recording_id) VALUES (NEW.id)
                ON CONFLICT(recording_id) DO NOTHING;
            END;
            CREATE TRIGGER IF NOT EXISTS meeting_search_recording_update
            AFTER UPDATE ON recordings BEGIN
                INSERT INTO meeting_search_dirty(recording_id) VALUES (OLD.id)
                ON CONFLICT(recording_id) DO NOTHING;
                INSERT INTO meeting_search_dirty(recording_id) VALUES (NEW.id)
                ON CONFLICT(recording_id) DO NOTHING;
            END;
            CREATE TRIGGER IF NOT EXISTS meeting_search_recording_delete
            AFTER DELETE ON recordings BEGIN
                INSERT INTO meeting_search_dirty(recording_id) VALUES (OLD.id)
                ON CONFLICT(recording_id) DO NOTHING;
            END;

            CREATE TRIGGER IF NOT EXISTS meeting_search_transcription_insert
            AFTER INSERT ON transcriptions WHEN NEW.recording_id IS NOT NULL AND NEW.recording_id != '' BEGIN
                INSERT INTO meeting_search_dirty(recording_id) VALUES (NEW.recording_id)
                ON CONFLICT(recording_id) DO NOTHING;
            END;
            CREATE TRIGGER IF NOT EXISTS meeting_search_transcription_update
            AFTER UPDATE ON transcriptions BEGIN
                INSERT INTO meeting_search_dirty(recording_id)
                    SELECT OLD.recording_id WHERE OLD.recording_id IS NOT NULL AND OLD.recording_id != ''
                    ON CONFLICT(recording_id) DO NOTHING;
                INSERT INTO meeting_search_dirty(recording_id)
                    SELECT NEW.recording_id WHERE NEW.recording_id IS NOT NULL AND NEW.recording_id != ''
                    ON CONFLICT(recording_id) DO NOTHING;
            END;
            CREATE TRIGGER IF NOT EXISTS meeting_search_transcription_delete
            AFTER DELETE ON transcriptions WHEN OLD.recording_id IS NOT NULL AND OLD.recording_id != '' BEGIN
                INSERT INTO meeting_search_dirty(recording_id) VALUES (OLD.recording_id)
                ON CONFLICT(recording_id) DO NOTHING;
            END;

            CREATE TRIGGER IF NOT EXISTS meeting_search_analysis_insert
            AFTER INSERT ON analysis_runs BEGIN
                INSERT INTO meeting_search_dirty(recording_id)
                    SELECT COALESCE(NULLIF(NEW.recording_id, ''), CASE WHEN NEW.scope_type = 'recording' THEN NEW.scope_id END)
                    WHERE COALESCE(NULLIF(NEW.recording_id, ''), CASE WHEN NEW.scope_type = 'recording' THEN NEW.scope_id END) IS NOT NULL
                    ON CONFLICT(recording_id) DO NOTHING;
            END;
            CREATE TRIGGER IF NOT EXISTS meeting_search_analysis_update
            AFTER UPDATE ON analysis_runs BEGIN
                INSERT INTO meeting_search_dirty(recording_id)
                    SELECT COALESCE(NULLIF(OLD.recording_id, ''), CASE WHEN OLD.scope_type = 'recording' THEN OLD.scope_id END)
                    WHERE COALESCE(NULLIF(OLD.recording_id, ''), CASE WHEN OLD.scope_type = 'recording' THEN OLD.scope_id END) IS NOT NULL
                    ON CONFLICT(recording_id) DO NOTHING;
                INSERT INTO meeting_search_dirty(recording_id)
                    SELECT COALESCE(NULLIF(NEW.recording_id, ''), CASE WHEN NEW.scope_type = 'recording' THEN NEW.scope_id END)
                    WHERE COALESCE(NULLIF(NEW.recording_id, ''), CASE WHEN NEW.scope_type = 'recording' THEN NEW.scope_id END) IS NOT NULL
                    ON CONFLICT(recording_id) DO NOTHING;
            END;
            CREATE TRIGGER IF NOT EXISTS meeting_search_analysis_delete
            AFTER DELETE ON analysis_runs BEGIN
                INSERT INTO meeting_search_dirty(recording_id)
                    SELECT COALESCE(NULLIF(OLD.recording_id, ''), CASE WHEN OLD.scope_type = 'recording' THEN OLD.scope_id END)
                    WHERE COALESCE(NULLIF(OLD.recording_id, ''), CASE WHEN OLD.scope_type = 'recording' THEN OLD.scope_id END) IS NOT NULL
                    ON CONFLICT(recording_id) DO NOTHING;
            END;
            """
        )

        if schema_changed:
            conn.execute("DELETE FROM meeting_search_fts")
            conn.execute("DELETE FROM meeting_search_dirty")
            conn.execute(
                """
                INSERT INTO meeting_search_dirty(recording_id)
                SELECT id FROM recordings WHERE 1
                ON CONFLICT(recording_id) DO NOTHING
                """
            )
            conn.execute(
                """
                INSERT INTO meeting_search_meta(key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (SEARCH_SCHEMA_VERSION,),
            )

        # Heal databases copied/restored without the derived FTS rows.
        indexed = int(conn.execute("SELECT COUNT(*) FROM meeting_search_fts").fetchone()[0])
        recordings = int(conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0])
        dirty = int(conn.execute("SELECT COUNT(*) FROM meeting_search_dirty").fetchone()[0])
        if indexed + dirty < recordings:
            conn.execute(
                """
                INSERT INTO meeting_search_dirty(recording_id)
                SELECT id FROM recordings WHERE 1
                ON CONFLICT(recording_id) DO NOTHING
                """
            )

    def _refresh_dirty(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT recording_id FROM meeting_search_dirty ORDER BY recording_id"
        ).fetchall()
        for row in rows:
            recording_id = str(row["recording_id"])
            conn.execute(
                "DELETE FROM meeting_search_fts WHERE recording_id = ?",
                (recording_id,),
            )
            recording = conn.execute(
                "SELECT id, title, project_name, created_at FROM recordings WHERE id = ?",
                (recording_id,),
            ).fetchone()
            if recording is None:
                continue

            transcription = conn.execute(
                """
                SELECT text, analysis
                FROM transcriptions
                WHERE recording_id = ? AND hidden = 0 AND merged_into IS NULL
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """,
                (recording_id,),
            ).fetchone()
            transcript_text = str(transcription["text"] or "") if transcription else ""
            legacy_analysis = str(transcription["analysis"] or "") if transcription else ""

            note_rows = conn.execute(
                """
                SELECT a.result_markdown
                FROM analysis_runs AS a
                WHERE a.status = 'completed'
                  AND COALESCE(NULLIF(a.recording_id, ''), CASE WHEN a.scope_type = 'recording' THEN a.scope_id END) = ?
                  AND NOT EXISTS (
                    SELECT 1
                    FROM analysis_runs AS newer
                    WHERE newer.status = 'completed'
                      AND newer.analysis_type = a.analysis_type
                      AND COALESCE(NULLIF(newer.recording_id, ''), CASE WHEN newer.scope_type = 'recording' THEN newer.scope_id END) = ?
                      AND (newer.created_at > a.created_at OR (newer.created_at = a.created_at AND newer.id > a.id))
                  )
                ORDER BY a.analysis_type ASC
                """,
                (recording_id, recording_id),
            ).fetchall()
            notes_text = "\n".join(
                [legacy_analysis, *[str(item["result_markdown"] or "") for item in note_rows]]
            ).strip()

            conn.execute(
                """
                INSERT INTO meeting_search_fts(
                    recording_id, title, project_name, transcript_text, notes_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    recording_id,
                    str(recording["title"] or ""),
                    str(recording["project_name"] or ""),
                    transcript_text,
                    notes_text,
                    str(recording["created_at"] or ""),
                ),
            )

        conn.execute("DELETE FROM meeting_search_dirty")
