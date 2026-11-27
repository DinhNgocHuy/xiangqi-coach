"""Packaged sidecar contract: with XQC_EXIT_ON_STDIN_EOF=1 the server stops cleanly when stdin closes."""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_exits_gracefully_on_stdin_eof(tmp_path: Path) -> None:
    port = _free_port()
    env = {**os.environ, "XQC_PORT": str(port), "XQC_DB_PATH": str(tmp_path / "c.db"), "XQC_EXIT_ON_STDIN_EOF": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "app"], cwd=BACKEND, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    assert r.status == 200
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError("backend did not start")
        proc.stdin.close()
        proc.wait(timeout=10)
        err = proc.stderr.read()
    finally:
        proc.kill()
    assert proc.returncode == 0
    assert b"Application shutdown complete" in err
