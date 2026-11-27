from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import __version__

router = APIRouter()


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    db: Literal["ok", "error"]


@router.get("/health")
def health(request: Request) -> Health:
    try:
        request.app.state.db.execute("SELECT 1").fetchone()
        db: Literal["ok", "error"] = "ok"
    except Exception:
        db = "error"
    return Health(status="ok" if db == "ok" else "degraded", version=__version__, db=db)
