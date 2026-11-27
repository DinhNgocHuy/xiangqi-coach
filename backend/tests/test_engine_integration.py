"""Real Pikafish (engine/pikafish, fetched by scripts/fetch_pikafish.py). Skipped when the binary is missing."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.engine.evaluate import evaluate_move
from app.services.engine.manager import EngineManager, resolve_engine_path
from app.services.engine.uci import MATE_CP
from app.services.rules import xiangqi as rules
from test_engine import MATE_IN_ONE, MATE_MOVE

SETTINGS = Settings(db_path=Path(":memory:"))
pytestmark = [
    pytest.mark.engine,
    pytest.mark.skipif(not resolve_engine_path(SETTINGS).is_file(), reason="Pikafish not fetched"),
]


def _with_engine(fn):  # type: ignore[no-untyped-def]
    async def go():  # type: ignore[no-untyped-def]
        m = EngineManager(SETTINGS)
        try:
            return await fn(m)
        finally:
            await m.close()

    return asyncio.run(go())


def test_start_position_is_balanced() -> None:
    r = _with_engine(lambda m: m.analyze(rules.START_FEN, depth=12, multipv=2))
    print("start position:", r.lines[0].score_cp, r.best_move, r.depth)
    assert r.depth >= 12 and abs(r.lines[0].score_cp) <= 100
    assert r.best_move in rules.legal_moves(rules.START_FEN) and len(r.lines) == 2 and not r.warnings
    assert len(r.history) >= 3


def test_mate_in_one() -> None:
    r = _with_engine(lambda m: m.analyze(MATE_IN_ONE, depth=8))
    assert r.lines[0].mate == 1 and r.best_move == MATE_MOVE and r.lines[0].score_cp == MATE_CP - 1


def test_blunder_loses_cannon() -> None:
    f = rules.START_FEN
    for mv in ("h2e2", "h9g7"):
        f = rules.apply_move(f, mv)
    e = _with_engine(lambda m: evaluate_move(m, f, "e2e6", depth=12))
    print("blunder:", e.eval_before_cp, e.eval_after_cp, e.cp_loss, e.opponent_best_replies, e.notes)
    assert e.cp_loss > 200
    assert "g7e6" in e.opponent_best_replies and e.threats.capture and e.material_at_risk
    assert e.principal_variation[0] == e.opponent_best_replies[0]


def test_mating_move_and_api(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "c.db"))) as c:
        r = c.post("/engine/evaluate-move", json={"fen_before": MATE_IN_ONE, "move": MATE_MOVE, "depth": 8})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "pikafish" and body["cp_loss"] == 0 and body["eval_after_mate"] == 0
        assert body["opponent_best_replies"] == [] and body["best_move"] == MATE_MOVE
        assert c.get("/engine/status").json()["running"] is True
        a = c.post("/engine/analyze", json={"fen": rules.START_FEN, "depth": 6}).json()
        again = c.post("/engine/analyze", json={"fen": rules.START_FEN, "depth": 6}).json()
        assert not a["cached"] and again["cached"]
