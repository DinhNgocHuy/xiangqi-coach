"""Fake UCI engine for unit tests. Behaviour via env:

FAKE_UCI_MODE: normal | slow (waits for stop) | hang (ignores everything after go) | crash_once | crash
FAKE_UCI_LOG:  file receiving one event per line (start, go, OVERLAP, crashed)
FAKE_UCI_PVS:  ';'-separated PVs for multipv 1..n (default: legal lines from the start position); at most n lines
FAKE_UCI_PVS_B: same, used when Black is to move (default: FAKE_UCI_PVS)
FAKE_UCI_MATE: "k:n,..." -> multipv k reports "score mate n" instead of cp
FAKE_UCI_DELAY: seconds to "think" per go in normal mode (stdin input during that time = OVERLAP)
"""

import os
import select
import sys
import time

MODE = os.environ.get("FAKE_UCI_MODE", "normal")
LOG = os.environ.get("FAKE_UCI_LOG")
PVS_W = os.environ.get("FAKE_UCI_PVS", "h2e2 h9g7 h0g2;b2e2 b9c7;g3g4 g6g5").split(";")
PVS_B = os.environ["FAKE_UCI_PVS_B"].split(";") if os.environ.get("FAKE_UCI_PVS_B") else PVS_W
MATE = dict(kv.split(":") for kv in os.environ.get("FAKE_UCI_MATE", "").split(",") if kv)
PVS = PVS_W
DELAY = float(os.environ.get("FAKE_UCI_DELAY", "0"))
_buf = b""


def log(event: str) -> None:
    if LOG:
        with open(LOG, "a") as f:
            f.write(event + "\n")


def say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def readline(timeout: float | None = None) -> str | None:
    """Unbuffered line read on fd 0 so select() sees pending input. None = timeout."""
    global _buf
    while b"\n" not in _buf:
        if timeout is not None and not select.select([0], [], [], timeout)[0]:
            return None
        chunk = os.read(0, 4096)
        if not chunk:
            sys.exit(0)
        _buf += chunk
    line, _buf = _buf.split(b"\n", 1)
    return line.decode().strip()


def infos(depth: int, multipv: int) -> None:
    for d in range(1, depth + 1):
        for k in range(1, min(multipv, len(PVS)) + 1):
            score = f"mate {MATE[str(k)]}" if str(k) in MATE else f"cp {30 - 10 * k}"
            say(f"info depth {d} seldepth {d + 2} multipv {k} score {score} nodes {d * 100} pv {PVS[k - 1]}")


log("start")
multipv = 1
while True:
    cmd = readline()
    if cmd == "uci":
        say("id name FakeFish")
        say("uciok")
    elif cmd == "isready":
        say("readyok")
    elif cmd == "quit":
        sys.exit(0)
    elif cmd.startswith("position fen "):
        PVS = PVS_B if cmd.split()[3] == "b" else PVS_W
    elif cmd.startswith("setoption name MultiPV value"):
        multipv = int(cmd.split()[-1])
    elif cmd.startswith("go"):
        log("go")
        if MODE == "crash" or (MODE == "crash_once" and "crashed" not in open(LOG).read()):
            log("crashed")
            os._exit(3)
        if MODE == "hang":
            while True:
                readline()
        parts = cmd.split()
        depth = int(parts[2]) if parts[1] == "depth" else 5
        if MODE == "slow":
            infos(2, multipv)
            while readline() != "stop":
                log("OVERLAP")
        else:
            infos(depth, multipv)
            end = time.monotonic() + DELAY
            while (left := end - time.monotonic()) > 0:
                if readline(left) is not None:
                    log("OVERLAP")
        say(f"bestmove {PVS[0].split()[0]}")
