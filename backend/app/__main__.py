import os
import sys
import threading

import uvicorn

from app.core.config import Settings
from app.core.logging import configure_logging
from app.main import create_app


def stop_on_stdin(server: uvicorn.Server) -> None:
    """Graceful stop when the parent (Tauri) sends a line or closes our stdin: lifespan shutdown still runs."""
    try:
        sys.stdin.buffer.readline()
    except (OSError, ValueError):
        pass  # broken/closed pipe = parent is gone, stop too
    server.should_exit = True


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
            log_config=None,  # keep our JSON handler
        )
    )
    # Only for the packaged sidecar: a dev/CLI run must not stop when stdin is a closed terminal.
    if os.environ.get("XQC_EXIT_ON_STDIN_EOF") == "1" and sys.stdin is not None:
        threading.Thread(target=stop_on_stdin, args=(server,), daemon=True, name="stdin-watch").start()
    server.run()
    if not server.started:
        sys.exit(3)  # same as uvicorn.run: startup failed (e.g. port in use)


if __name__ == "__main__":
    main()
