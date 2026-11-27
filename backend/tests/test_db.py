import json
import sqlite3
from pathlib import Path

import pytest

from app.core import db
from app.services.rules import xiangqi as rules


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "sub" / "coach.db")
    yield c
    c.close()


def test_migrate_is_idempotent(conn: sqlite3.Connection) -> None:
    assert db.migrate(conn) == [1, 2, 3]
    assert db.migrate(conn) == []
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == [1, 2, 3]
    assert db.user_tables(conn) == [
        "engine_cache", "exercise_attempts", "exercises", "move_reviews", "moves", "sessions", "thinking_mistakes"
    ]


def test_foreign_keys_and_constraints(conn: sqlite3.Connection) -> None:
    db.migrate(conn)
    move = "INSERT INTO moves (session_id, move_number, side, uci, fen_before, fen_after, created_at) VALUES (?, ?, ?, 'h2e2', 'a', 'b', 't')"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(move, ("missing", 1, "w"))
    conn.execute("INSERT INTO sessions (id, started_at) VALUES ('s1', 't')")
    conn.execute(move, ("s1", 1, "w"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(move, ("s1", 1, "w"))  # UNIQUE(session_id, move_number)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(move, ("s1", 2, "x"))  # side CHECK


def test_failed_migration_rolls_back(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "_migrations", lambda: [(1, "0001_bad.sql", "CREATE TABLE t (a);\nNOT SQL;\n")])
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)
    assert db.user_tables(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_export_and_backup(conn: sqlite3.Connection, tmp_path: Path) -> None:
    db.migrate(conn)
    conn.execute("INSERT INTO sessions (id, started_at, note) VALUES ('s1', 't', 'ghi chú')")
    conn.execute("INSERT INTO engine_cache VALUES ('fen', 10, 1, '{}')")
    data = db.export_json(conn)
    json.dumps(data)
    assert data["sessions"] == [
        {"id": "s1", "started_at": "t", "ended_at": None, "note": "ghi chú", "start_fen": rules.START_FEN}
    ]
    assert data["engine_cache"] == [{"fen": "fen", "depth": 10, "multipv": 1, "result_json": "{}"}]
    assert data["moves"] == []

    copy = db.backup_to(conn, tmp_path / "backup" / "copy.db")
    other = sqlite3.connect(copy)
    try:
        assert other.execute("SELECT note FROM sessions").fetchone()[0] == "ghi chú"
    finally:
        other.close()
