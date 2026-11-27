"""Minimal async UCI client for one long-lived Pikafish process.

Knows the protocol only (handshake, options, go/stop, info parsing). Queueing, restarts, caching and
move validation live in manager.py.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MATE_CP = 30000  # mate in n (moves) -> +-(MATE_CP - n) centipawns, so mates always sort above any cp score


class EngineError(RuntimeError):
    """Engine process died, hung or answered nonsense."""


class EngineSilent(EngineError):
    """No output within the read timeout (process may still be alive)."""


@dataclass
class Info:
    multipv: int
    depth: int
    seldepth: int | None
    cp: int | None  # side-to-move perspective
    mate: int | None  # moves to mate, >0 = side to move mates
    nodes: int | None
    pv: list[str]

    @property
    def score_cp(self) -> int:
        """cp, or mate mapped to +-(MATE_CP - n). Use `mate` to tell them apart; never subtract two mapped mates."""
        if self.mate is None:
            return self.cp or 0
        return MATE_CP - abs(self.mate) if self.mate > 0 else -(MATE_CP - abs(self.mate))


def parse_info(line: str) -> Info | None:
    """Parse an `info ... score ... pv ...` line. Bound (aspiration fail) and pv-less lines -> None."""
    tokens = line.split()
    if not tokens or tokens[0] != "info" or "pv" not in tokens or "score" not in tokens:
        return None
    if "lowerbound" in tokens or "upperbound" in tokens:
        return None
    vals: dict[str, int] = {}
    cp = mate = None
    pv: list[str] = []
    i = 1
    try:
        while i < len(tokens):
            t = tokens[i]
            if t == "pv":
                pv = tokens[i + 1 :]
                break
            if t == "score":
                kind, value = tokens[i + 1], int(tokens[i + 2])
                if kind == "cp":
                    cp = value
                elif kind == "mate":
                    mate = value
                i += 3
                continue
            if t in ("depth", "seldepth", "multipv", "nodes"):
                vals[t] = int(tokens[i + 1])
                i += 2
                continue
            i += 1
    except (IndexError, ValueError):
        return None
    if "depth" not in vals or (cp is None and mate is None) or not pv:
        return None
    return Info(vals.get("multipv", 1), vals["depth"], vals.get("seldepth"), cp, mate, vals.get("nodes"), pv)


@dataclass
class SearchOutput:
    lines: dict[int, Info] = field(default_factory=dict)  # latest complete info per multipv index
    history: list[Info] = field(default_factory=list)  # multipv-1 info at each completed depth
    bestmove: str | None = None
    timed_out: bool = False


class UciEngine:
    def __init__(self, path: Path, options: Mapping[str, str | int], handshake_timeout: float = 10.0) -> None:
        self.path = path
        self.options = dict(options)
        self.handshake_timeout = handshake_timeout
        self.proc: asyncio.subprocess.Process | None = None
        self.name: str | None = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            str(self.path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self.path.parent),  # EvalFile default "pikafish.nnue" is resolved relative to cwd
            # windowed (PyInstaller --noconsole) parent: without this every engine start flashes a console window
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            await self.send("uci")
            async for line in self._lines(self.handshake_timeout):
                if line.startswith("id name "):
                    self.name = line[8:]
                if line == "uciok":
                    break
            for name, value in self.options.items():
                await self.send(f"setoption name {name} value {value}")
            await self.ready()
        except BaseException:
            await self.kill()
            raise

    async def send(self, cmd: str) -> None:
        if not self.alive or self.proc is None or self.proc.stdin is None:
            raise EngineError("engine process is not running")
        try:
            self.proc.stdin.write((cmd + "\n").encode())
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise EngineError(f"engine pipe closed: {e}") from e

    async def _readline(self, timeout: float) -> str:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            raw = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        except TimeoutError:
            raise EngineSilent(f"engine silent for {timeout:.1f}s") from None
        if not raw:
            raise EngineError("engine process exited")
        return raw.decode(errors="replace").strip()

    async def _lines(self, timeout: float) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            left = deadline - loop.time()
            if left <= 0:
                raise EngineError(f"engine did not answer within {timeout:.1f}s")
            yield await self._readline(left)

    async def ready(self, timeout: float | None = None) -> None:
        await self.send("isready")
        async for line in self._lines(timeout or self.handshake_timeout):
            if line == "readyok":
                return

    async def search(
        self,
        fen: str,
        *,
        depth: int | None,
        movetime_ms: int | None,
        multipv: int,
        timeout: float,
        stop_grace: float = 2.0,
    ) -> SearchOutput:
        """Run one search. On `timeout` sends `stop` and returns the partial result (timed_out=True).

        Raises EngineError if the engine dies or does not answer `stop` within `stop_grace`.
        """
        await self.send(f"setoption name MultiPV value {multipv}")
        await self.send(f"position fen {fen}")
        await self.send("go " + (f"movetime {movetime_ms}" if movetime_ms else f"depth {depth}"))
        out = SearchOutput()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            left = deadline - loop.time()
            if left <= 0 and not out.timed_out:
                out.timed_out = True
                await self.send("stop")
                deadline = loop.time() + stop_grace
                continue
            if left <= 0:
                raise EngineError("engine ignored stop")
            try:
                line = await self._readline(left)
            except EngineSilent:
                if out.timed_out:
                    raise EngineError("engine ignored stop") from None
                continue  # loop sends stop
            if line.startswith("bestmove"):
                parts = line.split()
                out.bestmove = parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
                return out
            info = parse_info(line)
            if info is None:
                continue
            out.lines[info.multipv] = info
            if info.multipv == 1:
                if out.history and out.history[-1].depth == info.depth:
                    out.history[-1] = info
                else:
                    out.history.append(info)

    async def quit(self, timeout: float = 2.0) -> None:
        if not self.alive or self.proc is None:
            return
        try:
            await self.send("quit")
            await asyncio.wait_for(self.proc.wait(), timeout)
        except (EngineError, TimeoutError):
            await self.kill()

    async def kill(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.kill()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except TimeoutError:
                log.warning("engine did not exit after kill")

