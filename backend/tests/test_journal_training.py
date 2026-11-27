"""Phase F: move reviews, Thinking Journal, Training Center (fake + real engine), stats, export/backup."""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services import training as trn
from app.services.engine.manager import AnalysisResult, PvLine, resolve_engine_path
from app.services.rules import xiangqi as rules

FAKE = Path(__file__).with_name("fake_uci.py")
COMPS = ("threatAwareness", "responsePrediction", "variationCalculation", "positionEvaluation", "pieceSafety")
# Red moves at the start position; Black replies after 1. h2e2 (the fake engine picks by side to move).
PVS = "h2e2 h9g7;b2e2"
PVS_B = "h9g7 h0g2;b7b0;g6g5"
AFTER_H2E2 = rules.apply_move(rules.START_FEN, "h2e2")


def _review(sid: str, n: int, move: str, comps: dict[str, float | None] | None = None, **kw: Any) -> dict[str, Any]:
    c = {k: None for k in COMPS} | (comps or {})
    return {
        "session_id": sid, "move_number": n, "board_before": "x", "board_after": "y", "player_move": move,
        "player_intention": "", "move_quality_score": kw.get("quality"), "thinking_quality_score": kw.get("thinking"),
        "thinking_components": c, "strengths": [], "missed_threats": kw.get("missed", []), "learning_notes": [],
        "next_training_topic": "", "confidence": "low", "created_at": "2026-11-27T00:00:00Z",
        "engine": None, "self_assessment": {"skipped": False},
    }  # fmt: skip


def _session(c: TestClient, *moves: str) -> str:
    sid = c.post("/sessions", json={}).json()["id"]
    for m in moves:
        assert c.post(f"/sessions/{sid}/moves", json={"uci": m}).status_code == 201
    return sid


@pytest.fixture
def client(tmp_path: Path):  # type: ignore[no-untyped-def]
    with TestClient(create_app(Settings(db_path=tmp_path / "c.db", pikafish_path=tmp_path / "missing"))) as c:
        yield c


@pytest.fixture
def fake_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    if sys.platform == "win32":
        pytest.skip("fake engine uses a shebang script")
    exe = tmp_path / "fakefish"
    exe.write_text(f"#!{sys.executable}\nexec(compile(open({str(FAKE)!r}).read(), 'fake_uci', 'exec'))\n")
    exe.chmod(0o755)
    monkeypatch.setenv("FAKE_UCI_MODE", "normal")
    monkeypatch.setenv("FAKE_UCI_PVS", PVS)
    monkeypatch.setenv("FAKE_UCI_PVS_B", PVS_B)
    with TestClient(create_app(Settings(db_path=tmp_path / "c.db", pikafish_path=exe))) as c:
        yield c


def _db(c: TestClient) -> sqlite3.Connection:
    return c.app.state.db  # type: ignore[attr-defined]


# ---------------------------------------------------------------- reviews + mistakes


def test_review_upsert_and_mistake_derivation(client: TestClient) -> None:
    sid = _session(client, "h2e2", "h9g7")
    missed = ["Bạn dự đoán b9c7, nhưng đó chưa phải phản ứng mạnh nhất của đối thủ."]
    body = _review(sid, 1, "h2e2", {"responsePrediction": 0.5, "threatAwareness": 1, "pieceSafety": 0}, missed=missed)
    r = client.post(f"/sessions/{sid}/reviews", json=body)
    assert r.status_code == 201, r.text
    assert sorted(r.json()["mistakes"]) == ["pieceSafety", "responsePrediction"]  # null + 1 are not mistakes
    assert r.json()["review"]["self_assessment"] == {"skipped": False}  # extras kept

    items = client.get("/journal/mistakes").json()["items"]
    by = {m["component"]: m for m in items}
    assert by["responsePrediction"]["description"] == missed[0]
    assert "An toàn quân cờ" in by["pieceSafety"]["description"]  # fallback text
    assert all(m["fen"] == rules.START_FEN for m in items)  # fen_before of the recorded move

    # Upsert: same move, now perfect -> one review, mistakes removed.
    body = _review(sid, 1, "h2e2", {k: 1 for k in COMPS}, thinking=100)
    assert client.post(f"/sessions/{sid}/reviews", json=body).status_code == 201
    reviews = client.get(f"/sessions/{sid}/reviews").json()
    assert len(reviews) == 1 and reviews[0]["thinking_quality_score"] == 100 and reviews[0]["mistakes"] == []
    assert client.get("/journal/mistakes").json()["total"] == 0


def test_review_validation(client: TestClient) -> None:
    sid = _session(client, "h2e2")
    ok = _review(sid, 1, "h2e2")
    assert client.post("/sessions/nope/reviews", json=_review("nope", 1, "h2e2")).status_code == 404
    assert client.post(f"/sessions/{sid}/reviews", json=_review(sid, 2, "h9g7")).status_code == 404  # no move 2
    assert client.post(f"/sessions/{sid}/reviews", json=_review(sid, 1, "b2e2")).status_code == 400  # wrong move
    assert client.post(f"/sessions/{sid}/reviews", json=_review("other", 1, "h2e2")).status_code == 400
    bad = ok | {"thinking_components": {"threatAwareness": 2}}
    assert client.post(f"/sessions/{sid}/reviews", json=bad).status_code == 422
    assert client.post(f"/sessions/{sid}/reviews", json={k: v for k, v in ok.items() if k != "confidence"}).status_code == 422
    assert client.get("/sessions/nope/reviews").status_code == 404


def test_mistake_filters_and_paging(client: TestClient) -> None:
    sid = _session(client, "h2e2", "h9g7", "h0g2")
    for n, mv in enumerate(["h2e2", "h9g7", "h0g2"], 1):
        client.post(f"/sessions/{sid}/reviews", json=_review(sid, n, mv, {"responsePrediction": 0, "threatAwareness": 0}))
    _db(client).execute("UPDATE thinking_mistakes SET created_at = '2026-01-05T10:00:00+00:00' WHERE move_number = 1")
    page = client.get("/journal/mistakes", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 6 and len(page["items"]) == 2
    assert client.get("/journal/mistakes", params={"component": "threatAwareness"}).json()["total"] == 3
    jan = client.get("/journal/mistakes", params={"date_from": "2026-01-05", "date_to": "2026-01-05"}).json()
    assert jan["total"] == 2 and {m["move_number"] for m in jan["items"]} == {1}
    assert client.get("/journal/mistakes", params={"component": "bogus"}).status_code == 422


def test_patterns_recurring_and_trend(client: TestClient) -> None:
    assert client.get("/journal/patterns").json()["message"] == "Chưa có dữ liệu"
    moves = ["h2e2", "h9g7", "h0g2", "i9h9"]
    sid = _session(client, *moves)
    scores = [0.0, 0.0, 1.0, 0.5]  # responsePrediction per move
    for n, (mv, s) in enumerate(zip(moves, scores, strict=True), 1):
        client.post(f"/sessions/{sid}/reviews", json=_review(sid, n, mv, {"responsePrediction": s, "pieceSafety": 1}))
    db = _db(client)
    for n, ts in [(1, "2026-11-02T10:00:00+00:00"), (2, "2026-11-03T10:00:00+00:00")]:  # ISO week 45
        db.execute("UPDATE move_reviews SET created_at = ? WHERE move_number = ?", (ts, n))
        db.execute("UPDATE thinking_mistakes SET created_at = ? WHERE move_number = ?", (ts, n))
    for n in (3, 4):  # week 47
        db.execute("UPDATE move_reviews SET created_at = '2026-11-17T10:00:00+00:00' WHERE move_number = ?", (n,))

    p = {c["component"]: c for c in client.get("/journal/patterns").json()["components"]}
    rp = p["responsePrediction"]
    assert rp["count"] == 3 and rp["share"] == 1.0 and rp["recurring"] is True
    assert rp["trend"] == [
        {"week": "2026-W45", "avg_score": 0.0, "samples": 2},
        {"week": "2026-W47", "avg_score": 0.75, "samples": 2},
    ]
    assert rp["direction"] == "improving"
    assert p["pieceSafety"]["count"] == 0 and p["pieceSafety"]["recurring"] is False
    assert p["pieceSafety"]["direction"] == "flat"
    assert p["threatAwareness"]["trend"] == [] and p["threatAwareness"]["direction"] == "insufficient_data"


# ---------------------------------------------------------------- stats


def test_stats_empty(client: TestClient) -> None:
    s = client.get("/stats/summary").json()
    assert s["message"] == "Chưa có dữ liệu" and s["total_sessions"] == 0 and s["total_reviewed_moves"] == 0
    assert s["avg_thinking_score"] is None and s["avg_move_quality"] is None
    assert s["weekly"] == s["monthly"] == s["skills_to_improve"] == s["common_mistakes"] == []
    assert "Chưa đủ dữ liệu" in s["skills_message"]


def test_stats_populated(client: TestClient) -> None:
    moves = ["h2e2", "h9g7", "h0g2", "i9h9", "i0h0", "b9c7"]
    sid = _session(client, *moves)
    for n, mv in enumerate(moves, 1):
        thinking = None if n == 6 else 50 + n
        comps = {k: 1.0 for k in COMPS} | {"positionEvaluation": 0.5} if thinking else {"responsePrediction": 0}
        client.post(f"/sessions/{sid}/reviews", json=_review(sid, n, mv, comps, thinking=thinking, quality=80))
    s = client.get("/stats/summary").json()
    assert s["message"] is None and s["total_sessions"] == 1 and s["total_reviewed_moves"] == 6
    assert s["avg_thinking_score"] == 53.0 and s["thinking_samples"] == 5 and s["null_thinking_reviews"] == 1
    assert s["avg_move_quality"] == 80.0
    assert s["common_mistakes"][0] == {"component": "positionEvaluation", "label": "Đánh giá thế cờ", "count": 5}
    assert len(s["weekly"]) == 1 and s["weekly"][0]["reviews"] == 6 and s["weekly"][0]["avg_thinking"] == 53.0
    assert len(s["monthly"]) == 1 and s["monthly"][0]["reviews"] == 6 and len(s["monthly"][0]["period"]) == 7
    # 5 samples each for answered components; responsePrediction has 6 (one 0) -> lowest after positionEvaluation.
    assert [k["component"] for k in s["skills_to_improve"]] == ["positionEvaluation", "responsePrediction"]
    assert s["skills_message"] is None


# ---------------------------------------------------------------- export / backup


def test_export_and_backup(client: TestClient, tmp_path: Path) -> None:
    sid = _session(client, "h2e2")
    client.post(f"/sessions/{sid}/reviews", json=_review(sid, 1, "h2e2", {"threatAwareness": 0}))
    r = client.get("/data/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    tables = r.json()["tables"]
    assert len(tables["sessions"]) == 1 and len(tables["thinking_mistakes"]) == 1 and "exercises" in tables
    b = client.post("/data/backup")
    assert b.status_code == 201
    path = Path(b.json()["path"])
    assert path.parent == tmp_path and path.suffix == ".db"
    copy = sqlite3.connect(path)
    assert copy.execute("SELECT COUNT(*) FROM move_reviews").fetchone()[0] == 1
    copy.close()


def test_backup_keeps_newest_ten(client: TestClient, tmp_path: Path) -> None:
    paths = [client.post("/data/backup").json()["path"] for _ in range(12)]
    left = sorted(str(p) for p in tmp_path.glob("coach-backup-*.db"))
    assert left == paths[-10:]


def test_review_text_length_capped(client: TestClient) -> None:
    sid = _session(client, "h2e2")
    r = client.post(f"/sessions/{sid}/reviews", json=_review(sid, 1, "h2e2", missed=["x" * 501]))
    assert r.status_code == 422


# ---------------------------------------------------------------- training


def _mistakes(c: TestClient, sid: str, comps: dict[str, float]) -> None:
    assert c.post(f"/sessions/{sid}/reviews", json=_review(sid, 1, "h2e2", comps)).status_code == 201


def test_training_engine_unavailable(client: TestClient) -> None:
    assert client.post("/training/generate").json()["reason"] == "Chưa có lỗi tư duy nào để tạo bài tập."
    sid = _session(client, "h2e2")
    _mistakes(client, sid, {"responsePrediction": 0})
    r = client.post("/training/generate", json={}).json()
    assert r["created"] == [] and "Pikafish" in r["reason"]
    assert client.get("/training/exercises").json() == []


def test_training_generate_and_grade(fake_client: TestClient) -> None:
    c = fake_client
    sid = _session(c, "h2e2")
    _mistakes(c, sid, {k: 0 for k in COMPS})
    r = c.post("/training/generate", json={"limit": 10}).json()
    assert r["skipped"] == [], r
    ex = {e["type"]: e for e in r["created"]}
    assert set(ex) == {"threat_detection", "response_prediction", "variation_calculation", "position_evaluation",
                       "defensive_awareness"}  # fmt: skip
    for e in ex.values():
        assert e["status"] == "pending" and e["solution"] is None and e["engine_depth"] == 12
        assert e["session_id"] == sid and e["move_number"] == 1
        rules.legal_moves(e["fen"])  # valid position
    rp = ex["response_prediction"]
    assert rp["fen"] == AFTER_H2E2 and rp["side_to_move"] == "b" and "h9g7" not in rp["prompt"]
    assert ex["variation_calculation"]["fen"] == rules.START_FEN and ex["variation_calculation"]["played_move"] is None

    # Duplicates are skipped.
    again = c.post("/training/generate", json={"limit": 10}).json()
    assert again["created"] == [] and len(c.get("/training/exercises").json()) == 5

    # Grading: illegal -> 400 (not stored), incorrect, correct, solution revealed.
    url = f"/training/exercises/{rp['id']}/attempt"
    assert c.post(url, json={"answer": "h2e2"}).status_code == 400  # Red move, Black to play
    assert c.post("/training/exercises/9999/attempt", json={"answer": "a6a5"}).status_code == 404
    wrong = c.post(url, json={"answer": "a6a5"}).json()
    assert wrong["correct"] is False and wrong["explanation"].startswith("Chưa đúng")
    sol = wrong["exercise"]["solution"]
    assert sol["accepted_moves"] == ["h9g7", "b7b0", "g6g5"] and sol["best_move"] == "h9g7"
    assert all(rules.is_legal(AFTER_H2E2, m) for m in sol["accepted_moves"])
    right = c.post(url, json={"answer": "B7B0"}).json()
    assert right["correct"] is True and right["exercise"]["status"] == "done" and len(right["exercise"]["attempts"]) == 2

    assert ex["threat_detection"]["id"] and c.post(
        f"/training/exercises/{ex['threat_detection']['id']}/attempt", json={"answer": "b7b0"}
    ).json()["exercise"]["solution"]["accepted_moves"] == ["b7b0"]  # only the capture counts as a threat

    pe = f"/training/exercises/{ex['position_evaluation']['id']}/attempt"
    assert c.post(pe, json={"answer": "a6a5"}).status_code == 400
    assert c.post(pe, json={"answer": "better"}).json()["correct"] is False
    ok = c.post(pe, json={"answer": "equal"}).json()
    assert ok["correct"] is True and ok["exercise"]["solution"]["player_eval_cp"] == -20

    vc = c.post(f"/training/exercises/{ex['variation_calculation']['id']}/attempt", json={"answer": "b2e2"}).json()
    assert vc["correct"] is True and vc["exercise"]["played_move"] == "h2e2"

    statuses = [e["status"] for e in c.get("/training/exercises", params={"status": "pending"}).json()]
    assert statuses == ["pending"]  # defensive_awareness untouched
    assert len(c.get("/training/exercises", params={"status": "done"}).json()) == 4
    rows = _db(c).execute("SELECT COUNT(*) FROM exercise_attempts").fetchone()[0]
    assert rows == 6  # 400s are not stored


def test_undo_removes_review_mistakes_and_exercises(fake_client: TestClient) -> None:
    c = fake_client
    sid = _session(c, "h2e2")
    _mistakes(c, sid, {"responsePrediction": 0})
    ex = c.post("/training/generate", json={}).json()["created"]
    assert len(ex) == 1
    assert c.post(f"/training/exercises/{ex[0]['id']}/attempt", json={"answer": "h9g7"}).status_code == 200
    assert c.delete(f"/sessions/{sid}/moves/last").status_code == 200
    assert c.post(f"/sessions/{sid}/moves", json={"uci": "b2e2"}).status_code == 201  # replacement move 1
    assert c.get(f"/sessions/{sid}/reviews").json() == []
    assert c.get("/journal/mistakes").json()["total"] == 0
    assert c.get("/training/exercises").json() == []
    assert _db(c).execute("SELECT COUNT(*) FROM exercise_attempts").fetchone()[0] == 0


def test_training_skips_analysis_with_warnings(fake_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_UCI_PVS_B", "h9g7;a0a5")  # a0a5 is a Red move: illegal for Black -> warning
    sid = _session(fake_client, "h2e2")
    _mistakes(fake_client, sid, {"responsePrediction": 0})
    r = fake_client.post("/training/generate", json={}).json()
    assert r["created"] == [] and "cảnh báo" in r["skipped"][0]["reason"]


def _result(*lines: tuple[str, int, int | None]) -> AnalysisResult:
    pv = [PvLine(multipv=i + 1, score_cp=cp, mate=mate, depth=12, seldepth=None, nodes=None, pv=[m])
          for i, (m, cp, mate) in enumerate(lines)]  # fmt: skip
    return AnalysisResult(fen="x", depth_requested=12, movetime_ms=None, multipv=len(pv), depth=12,
                          best_move=pv[0].pv[0], lines=pv, history=[])  # fmt: skip


def test_accepted_moves_with_mates() -> None:
    # Mate in 2: mate in 3 is accepted, mate in 4 and any cp line are not (no subtraction of mapped mate scores).
    r = _result(("a", 29998, 2), ("b", 29997, 3), ("c", 29996, 4), ("d", 900, None))
    assert trn._accepted(r) == ["a", "b"]
    # Being mated: the longest defence (mated in 5) and mated in 4 are accepted, mated in 3 is not.
    r = _result(("a", -29995, -5), ("b", -29996, -4), ("c", -29997, -3))
    assert trn._accepted(r) == ["a", "b"]
    # cp best: a line that gets mated is never "within ACCEPT_CP".
    assert trn._accepted(_result(("a", 10, None), ("b", -5, None), ("c", -29990, -10))) == ["a", "b"]
    assert trn._eval_text({"player_eval_cp": 29995, "player_mate": 5}) == "bạn chiếu hết sau 5 nước"
    assert trn._eval_text({"player_eval_cp": -29997, "player_mate": -3}) == "bạn bị chiếu hết sau 3 nước"
    assert trn._eval_text({"player_eval_cp": -20, "player_mate": None}) == "-20 cp"


def test_training_limit_orders_by_frequency(fake_client: TestClient) -> None:
    c = fake_client
    sid = _session(c, "h2e2", "h9g7", "h0g2")
    c.post(f"/sessions/{sid}/reviews", json=_review(sid, 1, "h2e2", {"positionEvaluation": 0, "responsePrediction": 0}))
    c.post(f"/sessions/{sid}/reviews", json=_review(sid, 3, "h0g2", {"positionEvaluation": 0}))
    r = c.post("/training/generate", json={"limit": 1}).json()
    assert [e["type"] for e in r["created"]] == ["position_evaluation"]


@pytest.mark.engine
@pytest.mark.skipif(not resolve_engine_path(Settings(db_path=Path(":memory:"))).is_file(), reason="Pikafish not fetched")
def test_training_with_real_pikafish(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "c.db"))) as c:
        sid = _session(c, "h2e2", "h9g7", "e2e6")  # Red cannon blunders into the knight
        body = _review(sid, 3, "e2e6", {"responsePrediction": 0, "positionEvaluation": 0})
        assert c.post(f"/sessions/{sid}/reviews", json=body).status_code == 201
        r = c.post("/training/generate", json={"limit": 2}).json()
        assert len(r["created"]) == 2, r
        rp = next(e for e in r["created"] if e["type"] == "response_prediction")
        res = c.post(f"/training/exercises/{rp['id']}/attempt", json={"answer": "g7e6"}).json()
        print("real exercise:", json.dumps(res["exercise"]["solution"]))
        assert res["correct"] is True and res["exercise"]["engine_depth"] >= 10
        pe = next(e for e in r["created"] if e["type"] == "position_evaluation")
        assert c.post(f"/training/exercises/{pe['id']}/attempt", json={"answer": "worse"}).json()["correct"] is True
