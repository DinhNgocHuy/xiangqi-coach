"""Engine layer with a fake UCI engine (tests/fake_uci.py): parsing, queueing, timeout, restart, PV checks."""

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.engine import evaluate, manager
from app.services.engine.evaluate import cp_loss, is_stable
from app.services.engine.manager import AnalysisResult, DepthScore, EngineManager, EngineUnavailable
from app.services.engine.uci import MATE_CP, parse_info
from app.services.rules import xiangqi as rules

# ponytail: the fake engine is a shebang script; on Windows it would need a .bat/.exe wrapper.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="fake engine uses a shebang script")

FAKE = Path(__file__).with_name("fake_uci.py")


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    exe = tmp_path / "fakefish"
    exe.write_text(f"#!{sys.executable}\nexec(compile(open({str(FAKE)!r}).read(), 'fake_uci', 'exec'))\n")
    exe.chmod(0o755)
    log = tmp_path / "events.log"
    log.write_text("")
    monkeypatch.setenv("FAKE_UCI_LOG", str(log))
    monkeypatch.setattr(manager, "BACKOFF_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(manager, "STOP_GRACE_S", 0.3)

    def make(mode: str = "normal", timeout: float = 5.0, **env: str) -> EngineManager:
        monkeypatch.setenv("FAKE_UCI_MODE", mode)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from app.core import db

        conn = db.connect(":memory:")
        db.migrate(conn)
        return EngineManager(Settings(db_path=tmp_path / "x.db", pikafish_path=exe, engine_timeout_s=timeout), conn)

    make.events = lambda: log.read_text().split()  # type: ignore[attr-defined]
    return make


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def _analyze_and_close(m: EngineManager, *args, **kw) -> AnalysisResult:  # type: ignore[no-untyped-def]
    try:
        return await m.analyze(*args, **kw)
    finally:
        await m.close()


# ---------------------------------------------------------------- parsing


def test_parse_info() -> None:
    i = parse_info("info depth 12 seldepth 18 multipv 2 score cp -35 nodes 5000 nps 1 time 3 pv b2e2 b9c7")
    assert i is not None
    assert (i.multipv, i.depth, i.seldepth, i.cp, i.mate, i.nodes, i.pv) == (2, 12, 18, -35, None, 5000, ["b2e2", "b9c7"])
    m = parse_info("info depth 3 score mate -2 pv a0a1")
    assert m is not None and m.mate == -2 and m.score_cp == -(MATE_CP - 2) and m.multipv == 1
    assert parse_info("info depth 9 score cp 10 upperbound pv a0a1") is None
    assert parse_info("info depth 9 currmove h2e2 currmovenumber 1") is None
    assert parse_info("info string NNUE evaluation enabled") is None
    assert parse_info("info depth x score cp 1 pv a0a1") is None


# ---------------------------------------------------------------- manager with fake engine


def test_analyze_multipv_history_and_cache(fake) -> None:  # type: ignore[no-untyped-def]
    m = fake()

    async def go() -> tuple[AnalysisResult, AnalysisResult]:
        try:
            return await m.analyze(rules.START_FEN, depth=4, multipv=3), await m.analyze(rules.START_FEN, depth=4, multipv=3)
        finally:
            await m.close()

    r, again = run(go())
    assert r.depth == 4 and r.best_move == "h2e2" and not r.warnings and not r.cached
    assert [ln.pv for ln in r.lines] == [["h2e2", "h9g7", "h0g2"], ["b2e2", "b9c7"], ["g3g4", "g6g5"]]
    assert [ln.score_cp for ln in r.lines] == [20, 10, 0]
    assert [h.depth for h in r.history] == [1, 2, 3, 4]
    assert again.cached and again.lines == r.lines
    assert fake.events().count("go") == 1  # second call served from engine_cache
    assert fake.events().count("start") == 1


def test_illegal_pv_is_truncated(fake) -> None:  # type: ignore[no-untyped-def]
    # a0a5 is blocked by Red's own pawn on a3; z9z9 is not a move at all.
    m = fake(FAKE_UCI_PVS="h2e2 h9g7 a0a5 a9a8;z9z9 b9c7")
    r = run(_analyze_and_close(m, rules.START_FEN, depth=2, multipv=2))
    assert [ln.pv for ln in r.lines] == [["h2e2", "h9g7"]]  # line 2 dropped entirely
    assert len(r.warnings) == 2 and "a0a5" in r.warnings[0]
    assert run(_analyze_and_close(m, rules.START_FEN, depth=2, multipv=2)).cached is False  # never cache bad output


def test_timeout_sends_stop_and_returns_partial(fake) -> None:  # type: ignore[no-untyped-def]
    m = fake("slow", timeout=0.3)
    r = run(_analyze_and_close(m, rules.START_FEN, depth=20))
    assert r.timed_out and r.depth == 2 and r.best_move == "h2e2"
    assert "OVERLAP" not in fake.events()


def test_crash_restarts_engine(fake) -> None:  # type: ignore[no-untyped-def]
    m = fake("crash_once")
    r = run(_analyze_and_close(m, rules.START_FEN, depth=3))
    assert r.depth == 3
    assert fake.events().count("start") == 2 and m.restarts == 1 and m.last_error


@pytest.mark.parametrize("mode", ["crash", "hang"])
def test_gives_up_after_max_attempts(fake, mode: str) -> None:  # type: ignore[no-untyped-def]
    m = fake(mode, timeout=0.2)
    with pytest.raises(EngineUnavailable, match="không phản hồi"):
        run(_analyze_and_close(m, rules.START_FEN, depth=3))
    assert fake.events().count("start") == manager.MAX_ATTEMPTS


def test_requests_are_serialized(fake) -> None:  # type: ignore[no-untyped-def]
    m = fake(FAKE_UCI_DELAY="0.1")

    async def go() -> list[AnalysisResult]:
        try:
            return await asyncio.gather(*(m.analyze(rules.START_FEN, depth=d) for d in (2, 3, 4)))
        finally:
            await m.close()

    results = run(go())
    assert [r.depth for r in results] == [2, 3, 4]
    events = fake.events()
    assert events.count("go") == 3 and "OVERLAP" not in events and events.count("start") == 1


def test_missing_engine_and_game_over(tmp_path: Path) -> None:
    m = EngineManager(Settings(db_path=tmp_path / "x.db", pikafish_path=tmp_path / "nope"))
    with pytest.raises(EngineUnavailable, match="Chưa có Pikafish"):
        run(m.analyze(rules.START_FEN))
    assert m.status()["available"] is False
    fen = rules.apply_move(MATE_IN_ONE, MATE_MOVE)
    r = run(m.analyze(fen))  # no legal moves: answered by the rules adapter, engine not needed
    assert r.game_over == "checkmate" and r.lines == [] and r.best_move is None
    with pytest.raises(rules.FenError):
        run(m.analyze("not a fen"))


# Red to move: rook a8 holds rank 8, rook b0-b9 checks along rank 9 -> mate.
MATE_IN_ONE = "4k4/R8/9/9/9/9/9/9/9/1R1K5 w - - 0 1"
MATE_MOVE = "b0b9"


def test_mate_in_one_fixture_is_mate() -> None:
    assert rules.game_status(rules.apply_move(MATE_IN_ONE, MATE_MOVE)) == "checkmate"
    others = [m for m in rules.legal_moves(MATE_IN_ONE) if m != MATE_MOVE]
    assert all(rules.game_status(rules.apply_move(MATE_IN_ONE, m)) != "checkmate" for m in others)


# ---------------------------------------------------------------- evaluate helpers


def test_cp_loss_handles_mates() -> None:
    assert cp_loss(50, None, -250, None) == 300
    assert cp_loss(50, None, 80, None) == 0
    assert cp_loss(MATE_CP - 3, 3, MATE_CP - 5, 5) == 0  # slower mate is still a win
    assert cp_loss(-(MATE_CP - 2), -2, -(MATE_CP - 1), -1) == 0  # already lost
    assert cp_loss(MATE_CP - 3, 3, 400, None) == evaluate.MATE_CLAMP_CP - 400  # missed a forced mate
    assert cp_loss(0, None, -(MATE_CP - 1), -1) == evaluate.MATE_CLAMP_CP  # walked into mate


def test_material_at_risk() -> None:
    # Black to move: rook a9 can take the Red pawn on a5; Red rook a0 can take back.
    fen = "r2k5/9/9/9/P8/9/9/9/9/R3K4 b - - 0 1"
    assert evaluate._material_at_risk(fen, ["a9a5"])  # capture, PV shows no recapture
    assert evaluate._material_at_risk(fen, ["a9a5", "a0a1"])  # next ply is not a capture
    assert not evaluate._material_at_risk(fen, ["a9a5", "a0a5"])  # rook (900) recaptured for a pawn
    assert not evaluate._material_at_risk(fen, ["a9a8"])  # no capture
    assert not evaluate._material_at_risk(fen, [])


def _hist(*items: tuple[int, str]) -> AnalysisResult:
    return AnalysisResult(
        fen=rules.START_FEN, depth_requested=3, movetime_ms=None, multipv=1, depth=3, best_move="h2e2", lines=[],
        history=[DepthScore(depth=d + 1, score_cp=s, mate=None, best_move=b) for d, (s, b) in enumerate(items)],
    )  # fmt: skip


def test_is_stable() -> None:
    assert is_stable(_hist((10, "h2e2"), (25, "h2e2"), (40, "h2e2")))
    assert not is_stable(_hist((10, "h2e2"), (25, "h2e2"), (80, "h2e2")))
    assert not is_stable(_hist((10, "h2e2"), (25, "b2e2"), (30, "h2e2")))
    assert not is_stable(_hist((10, "h2e2"), (12, "h2e2")))


# ---------------------------------------------------------------- API (no engine binary)


def test_api_without_engine(tmp_path: Path) -> None:
    app = create_app(Settings(db_path=tmp_path / "c.db", pikafish_path=tmp_path / "missing"))
    with TestClient(app) as c:
        st = c.get("/engine/status").json()
        assert st["available"] is False and "Pikafish" in st["message"]
        r = c.post("/engine/analyze", json={"fen": rules.START_FEN})
        assert r.status_code == 503 and "Chưa có Pikafish" in r.json()["detail"]
        assert c.post("/engine/analyze", json={"fen": "xx"}).status_code == 400
        bad = c.post("/engine/evaluate-move", json={"fen_before": rules.START_FEN, "move": "a0a5"})
        assert bad.status_code == 400 and "Nước đi" in bad.json()["detail"]
        assert c.post("/engine/evaluate-move", json={"fen_before": rules.START_FEN, "move": "h2e2"}).status_code == 503
        assert c.post("/engine/analyze", json={"fen": rules.START_FEN, "multipv": 50}).status_code == 422


def test_frozen_build_uses_engine_next_to_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert manager.default_engine_dir() == manager.REPO_ENGINE_DIR
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "backend.exe"))
    assert manager.default_engine_dir() == manager.REPO_ENGINE_DIR  # no bundled dir -> fallback
    (tmp_path / "pikafish").mkdir()
    assert manager.default_engine_dir() == tmp_path / "pikafish"
    assert manager.resolve_engine_path(Settings(db_path=tmp_path / "x.db")).parent == tmp_path / "pikafish"
