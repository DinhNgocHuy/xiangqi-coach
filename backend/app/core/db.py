"""SQLite storage (stdlib sqlite3) with a numbered-file migration runner, JSON export and backup."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

# The app shares ONE connection between the threadpool and the event loop. Every write, transaction, backup and
# export holds this lock; otherwise a statement from another thread runs inside someone else's BEGIN…COMMIT (and is
# rolled back with it). RLock: a helper holding it may call another that takes it. Async code must not take it on
# the event loop; run the DB part with asyncio.to_thread instead.
db_lock = threading.RLock()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE … COMMIT under db_lock; ROLLBACK on any error."""
    with db_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: we manage transactions explicitly (BEGIN/COMMIT) in the migration runner.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrations() -> list[tuple[int, str, str]]:
    found = []
    for entry in resources.files("app.migrations").iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append((int(m[1]), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    versions = [v for v, _, _ in found]
    if len(set(versions)) != len(versions):
        raise RuntimeError(f"duplicate migration numbers: {versions}")
    return found


def _split_statements(sql: str) -> list[str]:
    """Split a script into statements (executescript would COMMIT our transaction)."""
    statements, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            statements.append(buf.strip())
            buf = ""
    if buf.strip():
        raise ValueError(f"incomplete SQL statement: {buf.strip()[:80]!r}")
    return statements


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations in order, each in its own transaction. Returns applied versions."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, name, sql in _migrations():
        if version in done:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split_statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now(UTC).isoformat()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        log.info("migration applied", extra={"version": version, "migration": name})
        applied.append(version)
    return applied


def user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name != 'schema_migrations' ORDER BY name"
    )
    return [r[0] for r in rows]


def export_json(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """All user tables as {table: [row dicts]}; JSON-serializable."""
    with db_lock:
        return {t: [dict(r) for r in conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] for t in user_tables(conn)}


def backup_to(conn: sqlite3.Connection, path: Path | str) -> Path:
    """Consistent copy of the live database via the SQLite online backup API."""
    dest_path = Path(path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(dest_path)
    try:
        with db_lock:
            conn.backup(dest)
    finally:
        dest.close()
    return dest_path
