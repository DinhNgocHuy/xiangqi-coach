"""Training Center: exercises from the player's own mistakes, solutions from Pikafish."""

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import training as trn

router = APIRouter(prefix="/training", tags=["training"])


class GenerateIn(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)


class AttemptIn(BaseModel):
    answer: str = Field(min_length=1, max_length=10)  # UCI move or better/equal/worse


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.post("/generate")
async def generate(request: Request, body: GenerateIn | None = None) -> dict[str, Any]:
    return await trn.generate(_db(request), request.app.state.engine, (body or GenerateIn()).limit)


@router.get("/exercises")
def exercises(request: Request, status: Literal["pending", "done"] | None = None) -> list[dict[str, Any]]:
    return trn.list_exercises(_db(request), status)


@router.post("/exercises/{exercise_id}/attempt")
def attempt(exercise_id: int, body: AttemptIn, request: Request) -> dict[str, Any]:
    try:
        return trn.attempt(_db(request), exercise_id, body.answer)
    except trn.ExerciseNotFound as e:
        raise HTTPException(404, "Không tìm thấy bài tập.") from e
    except trn.InvalidAnswer as e:
        raise HTTPException(400, str(e)) from e
