from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.api import ROUTERS
from app.core import db
from app.core.config import Settings
from app.services.engine.manager import EngineManager

log = logging.getLogger(__name__)

# Tauri WebView2 origins + Vite dev server. Nothing else may call the backend from a browser.
ALLOWED_ORIGINS = [
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "http://localhost:1420",
]
# Host header must name the loopback address (blocks DNS rebinding). Tests add "testserver" via monkeypatch.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
# State-changing requests must carry this header. A web page cannot add a custom header to a cross-site request
# without a CORS preflight, which only the origins above pass: this blocks "simple" cross-site POSTs (CSRF).
CLIENT_HEADER = "X-XQC-Client"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_JSON_BYTES = 2 * 1024 * 1024  # other bodies; vision uploads enforce their own 10 MB limit


class RequestGuard:
    """Pure ASGI: 403 without CLIENT_HEADER on writes; 413 for a non-multipart body over MAX_JSON_BYTES."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in WRITE_METHODS:
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if headers.get(CLIENT_HEADER.lower()) != "1":
            return await PlainTextResponse(f"Missing {CLIENT_HEADER} header", 403)(scope, receive, send)
        # Vision uploads (raw PNG or multipart) enforce their own 10 MB cap while streaming the body.
        if headers.get("content-type", "").startswith(("multipart/form-data", "image/png")):
            return await self.app(scope, receive, send)
        too_large = PlainTextResponse("Request body too large", 413)
        if int(headers.get("content-length") or 0) > MAX_JSON_BYTES:
            return await too_large(scope, receive, send)
        # Chunked/unknown length: read (at most the limit) up front, then replay it to the app.
        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > MAX_JSON_BYTES:
                return await too_large(scope, receive, send)
            if not message.get("more_body"):
                break

        async def replay() -> Message:
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        conn = db.connect(settings.db_path)
        try:
            applied = db.migrate(conn)
            log.info("database ready", extra={"db_path": str(settings.db_path), "migrations_applied": applied})
            app.state.db = conn
            # Pikafish starts lazily on the first analysis; a missing binary only makes /engine/* return 503.
            app.state.engine = EngineManager(settings, conn)
            yield
        finally:
            close = getattr(getattr(app.state, "coach_provider", None), "aclose", None)
            if close is not None:  # HTTP clients of the cached LLM provider
                await close()
            if hasattr(app.state, "engine"):
                await app.state.engine.close()
            conn.close()

    app = FastAPI(title="Xiangqi Coach backend", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", CLIENT_HEADER],
    )
    app.add_middleware(RequestGuard)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    for router in ROUTERS:
        app.include_router(router)
    return app
