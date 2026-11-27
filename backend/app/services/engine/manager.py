"""One long-lived Pikafish process behind a single analysis queue.

- Lazy start on the first request (the app starts even without the binary), UCI handshake, Threads/Hash options.
- One search at a time (asyncio.Lock = FIFO queue). Per-request timeout -> `stop` -> partial result.
- Process died / hung / ignored stop -> kill, restart with backoff, retry; after MAX_ATTEMPTS -> EngineUnavailable.
- Every PV is checked with the rules adapter and cut at the first illegal move (never pass on invented moves).
- Depth-based, complete results are cached in SQLite `engine_cache`.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.config import Settings
from app.core.db import db_lock
from app.services.engine.uci import EngineError, Info, SearchOutput, UciEngine
from app.services.rules import xiangqi as rules

log = logging.getLogger(__name__)

DEFAULT_DEPTH = 14
MAX_MULTIPV = 10
MAX_ATTEMPTS = 3
BACKOFF_S = (0.0, 0.5, 2.0)  # sleep before attempt 1, 2, 3
STOP_GRACE_S = 2.0
REPO_ENGINE_DIR = Path(__file__).resolve().parents[4] / "engine" / "pikafish"


def default_engine_dir() -> Path:
    """Frozen (PyInstaller) build: <exe dir>/pikafish if present; otherwise the repo's engine/pikafish."""
    if getattr(sys, "frozen", False) and (bundled := Path(sys.executable).parent / "pikafish").is_dir():
        return bundled
    return REPO_ENGINE_DIR


MSG_MISSING = (
    "Chưa có Pikafish. Chạy `backend/scripts/fetch_pikafish.py` hoặc đặt XQC_PIKAFISH_PATH tới file pikafish."
)


class EngineUnavailable(RuntimeError):
    """Engine binary missing or the process cannot be (re)started. Message is user-facing Vietnamese."""


class PvLine(BaseModel):
    multipv: int
    score_cp: int  # side-to-move perspective; mate mapped to +-(MATE_CP - n)
    mate: int | None  # moves to mate, >0 = side to move mates
    depth: int
    seldepth: int | None
    nodes: int | None
    pv: list[str]  # our UCI, validated by the rules adapter


class DepthScore(BaseModel):
    depth: int
    score_cp: int
    mate: int | None
    best_move: str | None


class AnalysisResult(BaseModel):
    fen: str
    depth_requested: int | None
    movetime_ms: int | None
    multipv: int
    depth: int  # depth reached by the best line (0 = no search: game over)
    best_move: str | None
    lines: list[PvLine]  # best first
    history: list[DepthScore]  # best line per completed depth, for stability checks
    game_over: Literal["checkmate", "stalemate"] | None = None
    timed_out: bool = False
    warnings: list[str] = []
    cached: bool = False


def resolve_engine_path(settings: Settings) -> Path:
    if settings.pikafish_path:
        return settings.pikafish_path
    return default_engine_dir() / ("pikafish.exe" if sys.platform == "win32" else "pikafish")


def _line(info: Info, pv: list[str]) -> PvLine:
    return PvLine(
        multipv=info.multipv, score_cp=info.score_cp, mate=info.mate, depth=info.depth,
        seldepth=info.seldepth, nodes=info.nodes, pv=pv,
    )  # fmt: skip


def _legal_prefix(fen: str, pv: list[str]) -> list[str]:
    bad = rules.validate_line(fen, pv)
    return pv if bad is None else pv[:bad]


def build_result(
    fen: str, out: SearchOutput, depth: int | None, movetime_ms: int | None, multipv: int
) -> AnalysisResult:
    warnings: list[str] = []
    lines: list[PvLine] = []
    for k in sorted(out.lines):
        info = out.lines[k]
        pv = _legal_prefix(fen, info.pv)
        if len(pv) < len(info.pv):
            warnings.append(f"PV {k}: engine move {info.pv[len(pv)]!r} is illegal, line cut at ply {len(pv)}")
            log.warning("illegal engine move", extra={"fen": fen, "pv": info.pv, "cut_at": len(pv)})
        if pv:
            lines.append(_line(info, pv))
    history = [
        DepthScore(depth=i.depth, score_cp=i.score_cp, mate=i.mate, best_move=(_legal_prefix(fen, i.pv[:1]) or [None])[0])
        for i in out.history
    ]
    best = out.bestmove if out.bestmove and rules.is_legal(fen, out.bestmove) else None
    if out.bestmove and best is None:
        warnings.append(f"bestmove {out.bestmove!r} is illegal, ignored")
    if best is None and lines:
        best = lines[0].pv[0]
    if out.timed_out:
        warnings.append("search stopped by timeout")
    return AnalysisResult(
        fen=fen, depth_requested=depth, movetime_ms=movetime_ms, multipv=multipv,
        depth=lines[0].depth if lines else 0, best_move=best, lines=lines, history=history,
        timed_out=out.timed_out, warnings=warnings,
    )  # fmt: skip


class EngineManager:
    def __init__(self, settings: Settings, conn: sqlite3.Connection | None = None) -> None:
        self.settings = settings
        self.path = resolve_engine_path(settings)
        self.conn = conn
        self.options: dict[str, str | int] = {"Threads": settings.engine_threads, "Hash": settings.engine_hash_mb}
        # No EvalFile: the engine runs with cwd = its own dir, so the default relative pikafish.nnue loads
        # (an absolute path breaks on non-ASCII Windows user folders).
        self._engine: UciEngine | None = None
        self._lock = asyncio.Lock()
        self.restarts = 0
        self.last_error: str | None = None

    # ------------------------------------------------------------ status / lifecycle

    def status(self) -> dict[str, object]:
        return {
            "available": self.path.is_file(),
            "running": bool(self._engine and self._engine.alive),
            "name": self._engine.name if self._engine else None,
            "path": str(self.path),
            "threads": self.settings.engine_threads,
            "hash_mb": self.settings.engine_hash_mb,
            "max_depth": self.settings.engine_max_depth,
            "max_movetime_ms": self.settings.engine_max_movetime_ms,
            "restarts": self.restarts,
            "last_error": self.last_error,
            "message": None if self.path.is_file() else MSG_MISSING,
        }

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.quit()
            self._engine = None

    async def _drop_engine(self, error: str) -> None:
        self.last_error = error
        if self._engine is not None:
            await self._engine.kill()
            self._engine = None

    # ------------------------------------------------------------ analysis

    async def analyze(
        self, fen: str, depth: int | None = None, movetime_ms: int | None = None, multipv: int = 1
    ) -> AnalysisResult:
        """Raises rules.FenError on a bad position, EngineUnavailable when the engine cannot be used."""
        fen = rules.to_fen(rules.parse_fen(fen))
        moves = rules.legal_moves(fen)  # also validates the position (FenError)
        if movetime_ms is not None:
            movetime_ms = max(1, min(movetime_ms, self.settings.engine_max_movetime_ms))
            depth = None
        else:
            depth = max(1, min(depth or DEFAULT_DEPTH, self.settings.engine_max_depth))
        multipv = max(1, min(multipv, MAX_MULTIPV))
        if not moves:
            return AnalysisResult(
                fen=fen, depth_requested=depth, movetime_ms=movetime_ms, multipv=multipv, depth=0,
                best_move=None, lines=[], history=[], game_over=rules.game_status(fen),
            )  # fmt: skip
        multipv = min(multipv, len(moves))
        # ponytail: key ignores move counters; Pikafish's 60-move rule could differ near the limit.
        key = " ".join(fen.split()[:2])
        if depth is not None and (hit := await asyncio.to_thread(self._cache_get, key, depth, multipv)):
            return hit.model_copy(update={"fen": fen, "cached": True})

        if movetime_ms is not None:
            timeout = movetime_ms / 1000 + 5
        else:
            timeout = self.settings.engine_timeout_s
        if not self.path.is_file():
            raise EngineUnavailable(MSG_MISSING)
        async with self._lock:
            out = await self._search_with_restarts(fen, depth, movetime_ms, multipv, timeout)
        result = build_result(fen, out, depth, movetime_ms, multipv)
        if depth is not None and not result.timed_out and result.depth >= depth and not result.warnings:
            await asyncio.to_thread(self._cache_put, key, depth, multipv, result)
        return result

    async def _search_with_restarts(
        self, fen: str, depth: int | None, movetime_ms: int | None, multipv: int, timeout: float
    ) -> SearchOutput:
        for attempt in range(MAX_ATTEMPTS):
            if BACKOFF_S[attempt]:
                await asyncio.sleep(BACKOFF_S[attempt])
            try:
                if self._engine is None or not self._engine.alive:
                    if self._engine is not None or attempt:
                        self.restarts += 1
                    self._engine = UciEngine(self.path, self.options)
                    await self._engine.start()
                    log.info("engine started", extra={"engine": self._engine.name, "path": str(self.path)})
                return await self._engine.search(
                    fen, depth=depth, movetime_ms=movetime_ms, multipv=multipv, timeout=timeout, stop_grace=STOP_GRACE_S
                )
            except (OSError, EngineError) as e:
                log.warning("engine failure", extra={"attempt": attempt + 1, "error": str(e)})
                await self._drop_engine(str(e))
            except asyncio.CancelledError:
                # A search may still be running; its output would leak into the next request.
                await self._drop_engine("request cancelled mid-search")
                raise
        raise EngineUnavailable(f"Pikafish không phản hồi sau {MAX_ATTEMPTS} lần thử: {self.last_error}")

    # ------------------------------------------------------------ cache (worker thread + db_lock: shared connection)

    def _cache_get(self, key: str, depth: int, multipv: int) -> AnalysisResult | None:
        if self.conn is None:
            return None
        with db_lock:
            row = self.conn.execute(
                "SELECT result_json FROM engine_cache WHERE fen = ? AND depth = ? AND multipv = ?",
                (key, depth, multipv),
            ).fetchone()
        return AnalysisResult.model_validate_json(row[0]) if row else None

    def _cache_put(self, key: str, depth: int, multipv: int, result: AnalysisResult) -> None:
        if self.conn is None:
            return
        with db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO engine_cache (fen, depth, multipv, result_json) VALUES (?, ?, ?, ?)",
                (key, depth, multipv, result.model_dump_json()),
            )
