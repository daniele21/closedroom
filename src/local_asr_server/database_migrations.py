from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Iterable


MigrationApply = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: MigrationApply


def ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Add one legacy-compatible column only when it is missing."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def apply_migrations(
    conn: sqlite3.Connection,
    *,
    component: str,
    migrations: Iterable[Migration],
) -> int:
    """Apply pending component migrations and persist one durable ledger row each.

    The caller owns the surrounding SQLite transaction. A failed migration therefore
    rolls back both its schema changes and ledger write with the caller's transaction.
    """
    normalized_component = component.strip()
    if not normalized_component:
        raise ValueError("migration component must be non-empty")

    ordered = sorted(tuple(migrations), key=lambda item: item.version)
    versions = [item.version for item in ordered]
    if any(version < 1 for version in versions):
        raise ValueError("migration versions must be positive")
    if len(versions) != len(set(versions)):
        raise ValueError(f"duplicate migration version for {normalized_component}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at REAL NOT NULL,
            PRIMARY KEY(component, version)
        )
        """
    )
    applied = {
        int(row[0])
        for row in conn.execute(
            "SELECT version FROM schema_migrations WHERE component = ?",
            (normalized_component,),
        ).fetchall()
    }
    applied_count = 0
    for migration in ordered:
        if migration.version in applied:
            continue
        migration.apply(conn)
        conn.execute(
            """
            INSERT INTO schema_migrations(component, version, name, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (normalized_component, migration.version, migration.name, time.time()),
        )
        applied_count += 1
    return applied_count
