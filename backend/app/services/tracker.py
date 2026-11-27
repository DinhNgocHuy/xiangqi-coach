"""Move Tracker: turns confirmed board placements into a move history per session (SQLite).

State lives only in the database (sessions.start_fen + moves), so `load()` rebuilds the tracker after a
restart. The tracker never guesses: a placement is recorded only when exactly one legal move of the side
to move produces it. A unique 2-ply match is returned as a suggestion the user must confirm by entering
both moves (`record_move`), never recorded automatically.

move_number is the ply index (1, 2, 3 …); side is the side that played it.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.db import db_lock, transaction
from app.services.rules import xiangqi as rules

Status = Literal["active", "ended", "checkmate", "stalemate"]


class SessionNotFound(LookupError):
    pass


class SessionConflict(RuntimeError):
    """Operation not allowed in the session's current state (ended, game over, no move to undo)."""


@dataclass
class Observation:
    result: Literal["recorded", "unchanged", "inconsistent"]
    move: dict[str, Any] | None = None
    reason: str | None = None
    suggestion: list[str] | None = None  # 2-ply line; user must confirm


@dataclass
class MoveTracker:
    id: str
    started_at: str
    ended_at: str | None
    note: str | None
    start_fen: str
    moves: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fen(self) -> str:
        return self.moves[-1]["fen_after"] if self.moves else self.start_fen

    @property
    def side_to_move(self) -> rules.Side:
        return rules.parse_fen(self.fen).side

    @property
    def game_status(self) -> rules.GameStatus | None:
        return rules.game_status(self.fen)

    @property
    def status(self) -> Status:
        return self.game_status or ("ended" if self.ended_at else "active")

    def classify(self, board: Sequence[Sequence[str | None]]) -> Observation:
        """Compare a confirmed placement with the current position. Pure: does not write."""
        target = rules.normalize_board(board)
        fen, side = self.fen, self.side_to_move
        if rules.parse_fen(fen).board == target:
            return Observation("unchanged")
        found = rules.find_move_between(fen, target, side)
        if len(found) == 1:
            return Observation("recorded", move={"uci": found[0]})
        if len(found) > 1:
            return Observation("inconsistent", reason=f"Nhiều nước hợp lệ cùng khớp: {', '.join(found)}")
        other = "b" if side == "w" else "w"
        if rules.find_move_between(fen, target, other):
            return Observation("inconsistent", reason=f"Thế cờ khớp với nước của bên không tới lượt ({other}).")
        lines = _two_ply_matches(fen, target)
        if len(lines) == 1:
            return Observation(
                "inconsistent",
                reason="Có vẻ đã đi 2 nước. Hãy xác nhận gợi ý trước khi ghi.",
                suggestion=lines[0],
            )
        problems = rules.validate_position(target)
        reason = "Không có nước hợp lệ nào dẫn tới thế cờ này."
        if len(lines) > 1:
            reason = f"Có {len(lines)} chuỗi 2 nước cùng khớp, không xác định được."
        elif problems:
            reason += " Thế cờ không hợp lệ: " + "; ".join(problems)
        return Observation("inconsistent", reason=reason)


def _two_ply_matches(fen: str, target: rules.Board) -> list[list[str]]:
    # Both moves' from-squares always end up changed, and 2 plies change at most 4 squares:
    # pruning on that keeps this to a few pyffish calls instead of ~2000 (seconds).
    board = rules.parse_fen(fen).board
    diff = {f"{rules.FILES[f]}{r}" for r in range(rules.RANKS) for f in range(9) if board[r][f] != target[r][f]}
    if len(diff) > 4:
        return []
    lines = []
    for m1 in rules.legal_moves(fen):
        if m1[:2] not in diff:
            continue
        mid = rules.apply_move(fen, m1)
        for m2 in rules.legal_moves(mid):
            if m2[:2] in diff and rules.parse_fen(rules.apply_move(mid, m2)).board == target:
                lines.append([m1, m2])
    return lines


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_start_fen(fen: str | None) -> str:
    """Validated full FEN; side to move must be given explicitly. Raises rules.FenError."""
    if fen is None:
        return rules.START_FEN
    pos = rules.parse_fen(fen)
    if len(fen.split()) < 2:
        raise rules.FenError("start FEN must include the side to move ('w' or 'b')")
    problems = rules.validate_position(pos.board, pos.side)
    if problems:
        raise rules.FenError("; ".join(problems))
    rules.legal_moves(fen)  # pyffish-level checks (raises FenError)
    return rules.to_fen(pos)


# ---------------------------------------------------------------- persistence


def create(conn: sqlite3.Connection, start_fen: str | None = None, note: str | None = None) -> MoveTracker:
    fen = normalize_start_fen(start_fen)
    sid = uuid.uuid4().hex
    with db_lock:
        conn.execute(
            "INSERT INTO sessions (id, started_at, note, start_fen) VALUES (?, ?, ?, ?)", (sid, _now(), note, fen)
        )
        return load(conn, sid)


def load(conn: sqlite3.Connection, session_id: str) -> MoveTracker:
    row = conn.execute(
        "SELECT id, started_at, ended_at, note, start_fen FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise SessionNotFound(session_id)
    moves = conn.execute(
        "SELECT move_number, side, uci, fen_before, fen_after, created_at FROM moves "
        "WHERE session_id = ? ORDER BY move_number",
        (session_id,),
    )
    return MoveTracker(**dict(row), moves=[dict(m) for m in moves])


def list_sessions(conn: sqlite3.Connection) -> list[MoveTracker]:
    ids = conn.execute("SELECT id FROM sessions ORDER BY started_at DESC, rowid DESC").fetchall()
    return [load(conn, r[0]) for r in ids]


def _open(tracker: MoveTracker) -> None:
    if tracker.ended_at:
        raise SessionConflict("Buổi tập đã kết thúc.")
    if tracker.game_status:
        raise SessionConflict(f"Ván cờ đã kết thúc ({tracker.game_status}).")


def _insert(conn: sqlite3.Connection, tracker: MoveTracker, uci: str) -> dict[str, Any]:
    fen_before = tracker.fen
    move = {
        "move_number": len(tracker.moves) + 1,
        "side": tracker.side_to_move,
        "uci": uci,
        "fen_before": fen_before,
        "fen_after": rules.apply_move(fen_before, uci),  # raises IllegalMoveError
        "created_at": _now(),
    }
    conn.execute(
        "INSERT INTO moves (session_id, move_number, side, uci, fen_before, fen_after, created_at) "
        "VALUES (:sid, :move_number, :side, :uci, :fen_before, :fen_after, :created_at)",
        {"sid": tracker.id, **move},
    )
    tracker.moves.append(move)
    return move


def record_move(conn: sqlite3.Connection, session_id: str, uci: str) -> dict[str, Any]:
    """Manual move entry; must be legal for the side to move."""
    with db_lock:
        tracker = load(conn, session_id)
        _open(tracker)
        return _insert(conn, tracker, uci)


def submit_position(
    conn: sqlite3.Connection, session_id: str, board: Sequence[Sequence[str | None]]
) -> Observation:
    with db_lock:
        tracker = load(conn, session_id)
        _open(tracker)
        obs = tracker.classify(board)
        if obs.result == "recorded":
            obs.move = _insert(conn, tracker, obs.move["uci"])  # type: ignore[index]
        return obs


def undo_last(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Delete the last move and everything keyed by its (session_id, move_number): review, thinking mistakes,
    exercises (their attempts cascade). Otherwise they would be attributed to the move that replaces it."""
    with transaction(conn):
        tracker = load(conn, session_id)
        if tracker.ended_at:
            raise SessionConflict("Buổi tập đã kết thúc.")
        if not tracker.moves:
            raise SessionConflict("Chưa có nước nào để hoàn tác.")
        last = tracker.moves[-1]
        for table in ("move_reviews", "thinking_mistakes", "exercises", "moves"):
            conn.execute(
                f"DELETE FROM {table} WHERE session_id = ? AND move_number = ?", (session_id, last["move_number"])
            )
        return last


def end(conn: sqlite3.Connection, session_id: str) -> MoveTracker:
    with db_lock:
        tracker = load(conn, session_id)
        if tracker.ended_at:
            raise SessionConflict("Buổi tập đã kết thúc.")
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (_now(), session_id))
        return load(conn, session_id)
