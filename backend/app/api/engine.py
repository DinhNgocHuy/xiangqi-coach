from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.engine.evaluate import MoveEvaluation, evaluate_move
from app.services.engine.manager import AnalysisResult, EngineManager, EngineUnavailable
from app.services.rules import xiangqi as rules

router = APIRouter(prefix="/engine", tags=["engine"])


class AnalyzeRequest(BaseModel):
    fen: str = Field(max_length=200)
    depth: int | None = Field(default=None, ge=1, le=99)  # clamped to XQC_ENGINE_MAX_DEPTH
    movetime_ms: int | None = Field(default=None, ge=1, le=600_000)  # clamped to XQC_ENGINE_MAX_MOVETIME_MS
    multipv: int = Field(default=1, ge=1, le=10)


class EvaluateRequest(BaseModel):
    fen_before: str = Field(max_length=200)
    move: str = Field(max_length=5)
    depth: int | None = Field(default=None, ge=1, le=99)


def _manager(request: Request) -> EngineManager:
    return request.app.state.engine


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    return _manager(request).status()


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, request: Request) -> AnalysisResult:
    try:
        return await _manager(request).analyze(body.fen, body.depth, body.movetime_ms, body.multipv)
    except rules.FenError as e:
        raise HTTPException(400, f"FEN không hợp lệ: {e}") from e
    except EngineUnavailable as e:
        raise HTTPException(503, str(e)) from e


@router.post("/evaluate-move")
async def evaluate(body: EvaluateRequest, request: Request) -> MoveEvaluation:
    try:
        return await evaluate_move(_manager(request), body.fen_before, body.move, body.depth)
    except rules.FenError as e:
        raise HTTPException(400, f"FEN không hợp lệ: {e}") from e
    except rules.IllegalMoveError as e:
        raise HTTPException(400, f"Nước đi không hợp lệ: {e}") from e
    except EngineUnavailable as e:
        raise HTTPException(503, str(e)) from e
