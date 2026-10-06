from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from local_asr_server.catalog import CATALOG_MIGRATIONS, CatalogStore
from local_asr_server.database_migrations import Migration, apply_migrations
from local_asr_server.jobs.job_store import JOB_MIGRATIONS, JobStore


class DatabaseMigrationTests(unittest.TestCase):
    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}

    def test_catalog_legacy_schema_is_upgraded_once_and_recorded(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE recordings (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE transcriptions (id TEXT PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE analysis_runs (id TEXT PRIMARY KEY, created_at REAL NOT NULL)"
        )

        first = apply_migrations(
            conn, component="catalog", migrations=CATALOG_MIGRATIONS
        )
        second = apply_migrations(
            conn, component="catalog", migrations=CATALOG_MIGRATIONS
        )

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertIn("capture_mode", self._columns(conn, "recordings"))
        self.assertIn("provider_options", self._columns(conn, "transcriptions"))
        self.assertIn("pipeline_run_id", self._columns(conn, "analysis_runs"))
        ledger = conn.execute(
            "SELECT component, version, name FROM schema_migrations"
        ).fetchall()
        self.assertEqual(
            ledger,
            [("catalog", 1, "legacy-capture-transcription-analysis-columns")],
        )

    def test_job_legacy_schema_is_upgraded_once_and_recorded(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                scope_type TEXT,
                scope_id TEXT,
                created_at REAL NOT NULL
            )
            """
        )

        first = apply_migrations(conn, component="jobs", migrations=JOB_MIGRATIONS)
        second = apply_migrations(conn, component="jobs", migrations=JOB_MIGRATIONS)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertIn("progress_detail_json", self._columns(conn, "jobs"))
        self.assertIn("dedupe_key", self._columns(conn, "jobs"))
        indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(jobs)")}
        self.assertIn("idx_jobs_dedupe", indexes)

    def test_catalog_and_jobs_share_one_namespaced_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closedroom.db"
            CatalogStore(db_path)
            JobStore(db_path)

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT component, version
                    FROM schema_migrations
                    ORDER BY component, version
                    """
                ).fetchall()
            self.assertEqual(rows, [("catalog", 1), ("jobs", 1)])

            CatalogStore(db_path)
            JobStore(db_path)
            with sqlite3.connect(db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(count, 2)

    def test_applied_version_name_cannot_be_rewritten(self) -> None:
        conn = sqlite3.connect(":memory:")
        apply_migrations(
            conn,
            component="catalog",
            migrations=(Migration(1, "original", lambda _conn: None),),
        )

        with self.assertRaisesRegex(RuntimeError, "migration history mismatch"):
            apply_migrations(
                conn,
                component="catalog",
                migrations=(Migration(1, "renamed", lambda _conn: None),),
            )

    def test_duplicate_component_versions_fail_before_mutating_schema(self) -> None:
        conn = sqlite3.connect(":memory:")
        calls: list[str] = []

        def first(_conn: sqlite3.Connection) -> None:
            calls.append("first")

        def duplicate(_conn: sqlite3.Connection) -> None:
            calls.append("duplicate")

        with self.assertRaisesRegex(ValueError, "duplicate migration version"):
            apply_migrations(
                conn,
                component="catalog",
                migrations=(
                    Migration(1, "first", first),
                    Migration(1, "duplicate", duplicate),
                ),
            )

        self.assertEqual(calls, [])
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        self.assertIsNone(table)


if __name__ == "__main__":
    unittest.main()
