"""HTTP routers. Later phases add their router here (e.g. vision, moves, engine, coach, training)."""

from fastapi import APIRouter

from app.api.coach import router as coach_router
from app.api.data import router as data_router
from app.api.engine import router as engine_router
from app.api.health import router as health_router
from app.api.journal import router as journal_router
from app.api.sessions import router as sessions_router
from app.api.training import router as training_router
from app.api.vision import router as vision_router

ROUTERS: list[APIRouter] = [health_router, engine_router, coach_router, sessions_router]
ROUTERS += [journal_router, training_router, data_router]
ROUTERS += [vision_router]
