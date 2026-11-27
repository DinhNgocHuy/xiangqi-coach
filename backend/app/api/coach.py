from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.services.coach.coach import NO_PROVIDER, CoachRequest, CoachResponse, coach_move
from app.services.coach.llm import LLMProvider, make_provider
from app.services.rules import xiangqi as rules

router = APIRouter(prefix="/coach", tags=["coach"])


def _provider(request: Request) -> LLMProvider | None:
    state = request.app.state
    if not hasattr(state, "coach_provider"):  # tests inject a FakeProvider here
        state.coach_provider = make_provider(state.settings)
    return state.coach_provider


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    p = _provider(request)
    if p is None:
        return {"available": False, "provider": None, "model": None, "reason": NO_PROVIDER + "."}
    return {"available": True, "provider": p.name, "model": p.model, "reason": None}


@router.post("/move-feedback")
async def move_feedback(body: CoachRequest, request: Request) -> CoachResponse:
    try:
        return await coach_move(body, _provider(request))
    except rules.FenError as e:
        raise HTTPException(400, f"FEN không hợp lệ: {e}") from e
    except rules.IllegalMoveError as e:
        raise HTTPException(400, f"Nước đi không hợp lệ: {e}") from e
