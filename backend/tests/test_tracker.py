import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.config import Settings
from app.main import create_app
from app.services import tracker as tr
from app.services.rules import xiangqi as rules

START = rules.START_FEN
# Red to play Ra0-a9#: Rb8 covers rank 8, flying-general rule covers the e-file.
MATE_IN_1 = "3k5/1R7/9/9/9/9/9/9/9/R3K4 w - - 0 1"


def board_after(fen: str, *ucis: str) -> rules.Board:
    for u in ucis:
        fen = rules.apply_move(fen, u)
    return rules.parse_fen(fen).board


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "coach.db")
    db.migrate(c)
    yield c
    c.close()


def test_record_unchanged_and_side_alternation(conn: sqlite3.Connection) -> None:
    s = tr.create(conn)
    assert (s.fen, s.side_to_move, s.status) == (START, "w", "active")
    assert tr.submit_position(conn, s.id, board_after(START)).result == "unchanged"

    obs = tr.submit_position(conn, s.id, board_after(START, "h2e2"))
    assert obs.result == "recorded"
    assert obs.move["move_number"] == 1 and obs.move["side"] == "w" and obs.move["uci"] == "h2e2"
    assert obs.move["fen_before"] == START

    obs = tr.submit_position(conn, s.id, board_after(START, "h2e2", "h9g7"))
    assert (obs.result, obs.move["side"], obs.move["move_number"]) == ("recorded", "b", 2)
    assert tr.load(conn, s.id).side_to_move == "w"


def test_capture_move(conn: sqlite3.Connection) -> None:
    s = tr.create(conn)
    obs = tr.submit_position(conn, s.id, board_after(START, "h2h9"))  # cannon takes knight
    assert obs.result == "recorded" and obs.move["uci"] == "h2h9"


def test_illegal_jump_is_inconsistent(conn: sqlite3.Connection) -> None:
    s = tr.create(conn)
    board = [list(r) for r in board_after(START)]
    board[5][0], board[0][0] = "R", None  # rook a0 -> a5 jumps over its own pawn
    obs = tr.submit_position(conn, s.id, board)
    assert obs.result == "inconsistent" and obs.move is None and obs.suggestion is None
    assert "Không có nước hợp lệ" in obs.reason
    assert tr.load(conn, s.id).moves == []


def test_wrong_side_moved(conn: sqlite3.Connection) -> None:
    s = tr.create(conn)
    black_first = rules.apply_move(START.replace(" w ", " b "), "h7e7")
    obs = tr.submit_position(conn, s.id, rules.parse_fen(black_first).board)
    assert obs.result == "inconsistent" and "không tới lượt" in obs.reason


def test_two_moves_is_suggestion_not_recorded(conn: sqlite3.Connection) -> None:
    s = tr.create(conn)
    obs = tr.submit_position(conn, s.id, board_after(START, "h2e2", "h9g7"))
    assert obs.result == "inconsistent"
    assert obs.suggestion == ["h2e2", "h9g7"]
    assert tr.load(conn, s.id).moves == []
    for u in obs.suggestion:  # user confirms by entering both moves
        tr.record_move(conn, s.id, u)
    assert tr.load(conn, s.id).fen == rules.apply_move(rules.apply_move(START, "h2e2"), "h9g7")


def test_game_end_blocks_further_moves(conn: sqlite3.Connection) -> None:
    s = tr.create(conn, MATE_IN_1)
    tr.record_move(conn, s.id, "a0a9")
    t = tr.load(conn, s.id)
    assert (t.status, t.side_to_move) == ("checkmate", "b")
    with pytest.raises(tr.SessionConflict):
        tr.record_move(conn, s.id, "d9d8")
    tr.undo_last(conn, s.id)  # correcting a mistake is still allowed
    assert tr.load(conn, s.id).status == "active"


def test_manual_move_validation_and_undo(conn: sqlite3.Connection) -> None:
    s = tr.create(conn)
    with pytest.raises(rules.IllegalMoveError):
        tr.record_move(conn, s.id, "a0a5")
    with pytest.raises(tr.SessionConflict):
        tr.undo_last(conn, s.id)
    tr.record_move(conn, s.id, "h2e2")
    assert tr.undo_last(conn, s.id)["uci"] == "h2e2"
    assert tr.load(conn, s.id).fen == START


def test_custom_start_fen_validation(conn: sqlite3.Connection) -> None:
    with pytest.raises(rules.FenError):
        tr.create(conn, START.split()[0])  # side to move missing
    with pytest.raises(rules.FenError):
        tr.create(conn, "4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1")  # kings facing
    s = tr.create(conn, MATE_IN_1.replace(" w ", " b "), note="tàn cuộc")
    assert (s.side_to_move, s.note) == ("b", "tàn cuộc")


def test_state_restored_after_reconnect(tmp_path: Path) -> None:
    c = db.connect(tmp_path / "coach.db")
    db.migrate(c)
    sid = tr.create(c).id
    tr.record_move(c, sid, "h2e2")
    tr.end(c, sid)
    c.close()

    c = db.connect(tmp_path / "coach.db")
    try:
        t = tr.load(c, sid)
        assert [m["uci"] for m in t.moves] == ["h2e2"]
        assert (t.side_to_move, t.status) == ("b", "ended")
        with pytest.raises(tr.SessionConflict):
            tr.record_move(c, sid, "h9g7")
    finally:
        c.close()


# ---------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(Settings(db_path=tmp_path / "coach.db"))) as c:
        yield c


def test_api_flow(client: TestClient) -> None:
    sid = client.post("/sessions", json={"note": "ván 1"}).json()["id"]
    second = client.post("/sessions", json={}).json()["id"]
    assert [s["id"] for s in client.get("/sessions").json()] == [second, sid]

    placement = rules.to_fen(rules.Position(board_after(START, "h2e2"), "w")).split()[0]
    r = client.post(f"/sessions/{sid}/positions", json={"fen_placement": placement})
    assert r.status_code == 200
    body = r.json()
    assert body["result"] == "recorded" and body["move"]["uci"] == "h2e2"
    assert body["session"]["side_to_move"] == "b"

    matrix = [list(row) for row in board_after(START, "h2e2")]
    assert client.post(f"/sessions/{sid}/positions", json={"placement": matrix}).json()["result"] == "unchanged"

    r = client.post(f"/sessions/{sid}/moves", json={"uci": "h9g7"})
    assert r.status_code == 201 and r.json()["side"] == "b"
    detail = client.get(f"/sessions/{sid}").json()
    assert detail["move_count"] == 2 and [m["uci"] for m in detail["moves"]] == ["h2e2", "h9g7"]

    assert client.delete(f"/sessions/{sid}/moves/last").json()["uci"] == "h9g7"
    assert client.post(f"/sessions/{sid}/end").json()["status"] == "ended"
    assert client.post(f"/sessions/{sid}/moves", json={"uci": "h9g7"}).status_code == 409
    assert client.post(f"/sessions/{sid}/end").status_code == 409


def test_api_errors(client: TestClient) -> None:
    assert client.get("/sessions/nope").status_code == 404
    assert client.post("/sessions/nope/moves", json={"uci": "h2e2"}).status_code == 404
    assert client.post("/sessions", json={"start_fen": "garbage"}).status_code == 400
    sid = client.post("/sessions", json={}).json()["id"]
    assert client.post(f"/sessions/{sid}/moves", json={"uci": "a0a5"}).status_code == 400
    assert client.post(f"/sessions/{sid}/positions", json={}).status_code == 400
    assert client.post(f"/sessions/{sid}/positions", json={"placement": [["K"]]}).status_code == 400
    assert client.delete(f"/sessions/{sid}/moves/last").status_code == 409
