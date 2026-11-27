"""Settings read from environment variables (prefix XQC_). See backend/.env.example."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

ENV_PREFIX = "XQC_"
HOST = "127.0.0.1"  # never configurable: the backend must not listen on other interfaces
DEFAULT_PORT = 8765
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def default_db_path(env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        base = env.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "XiangqiCoach" / "coach.db"
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "xiangqi-coach" / "coach.db"


@dataclass(frozen=True)
class Settings:
    port: int = DEFAULT_PORT
    db_path: Path = field(default_factory=default_db_path)
    pikafish_path: Path | None = None
    llm_api_key: str | None = field(default=None, repr=False)  # repr=False keeps it out of logs/tracebacks
    llm_model: str | None = None
    log_level: str = "INFO"
    engine_threads: int = field(default_factory=lambda: min(2, os.cpu_count() or 1))
    engine_hash_mb: int = 128
    engine_max_depth: int = 30
    engine_max_movetime_ms: int = 10_000
    engine_timeout_s: float = 30.0  # per analysis request; then "stop" and return the partial result
    host: str = field(default=HOST, init=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        def get(name: str) -> str | None:
            value = env.get(ENV_PREFIX + name, "").strip()
            return value or None

        port_raw = get("PORT")
        try:
            port = int(port_raw) if port_raw else DEFAULT_PORT
        except ValueError:
            raise ValueError(f"{ENV_PREFIX}PORT must be an integer, got {port_raw!r}") from None
        if not 1 <= port <= 65535:
            raise ValueError(f"{ENV_PREFIX}PORT out of range: {port}")

        log_level = (get("LOG_LEVEL") or "INFO").upper()
        if log_level not in LOG_LEVELS:
            raise ValueError(f"{ENV_PREFIX}LOG_LEVEL must be one of {LOG_LEVELS}, got {log_level!r}")

        def get_int(name: str, default: int, lo: int, hi: int) -> int:
            raw = get(name)
            try:
                value = int(raw) if raw else default
            except ValueError:
                raise ValueError(f"{ENV_PREFIX}{name} must be an integer, got {raw!r}") from None
            if not lo <= value <= hi:
                raise ValueError(f"{ENV_PREFIX}{name} out of range [{lo}, {hi}]: {value}")
            return value

        defaults = cls()
        db = get("DB_PATH")
        pikafish = get("PIKAFISH_PATH")
        return cls(
            port=port,
            db_path=Path(db).expanduser() if db else default_db_path(env),
            pikafish_path=Path(pikafish).expanduser() if pikafish else None,
            llm_api_key=get("LLM_API_KEY"),
            llm_model=get("LLM_MODEL"),
            log_level=log_level,
            engine_threads=get_int("ENGINE_THREADS", defaults.engine_threads, 1, 64),
            engine_hash_mb=get_int("ENGINE_HASH_MB", defaults.engine_hash_mb, 1, 4096),
            engine_max_depth=get_int("ENGINE_MAX_DEPTH", defaults.engine_max_depth, 1, 60),
            engine_max_movetime_ms=get_int("ENGINE_MAX_MOVETIME_MS", defaults.engine_max_movetime_ms, 100, 120_000),
        )
