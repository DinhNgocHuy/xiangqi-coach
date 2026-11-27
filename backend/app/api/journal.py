"""Move reviews, Thinking Journal (/journal/*) and Dashboard stats (/stats/*)."""

import sqlite3
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.review import MoveReviewIn, StoredReview
from app.services import journal as jr
from app.services import tracker as tr

router = APIRouter(tags=["journal"])

Component = Literal["threatAwareness", "responsePrediction", "variationCalculation", "positionEvaluation", "pieceSafety"]


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.post("/sessions/{session_id}/reviews", status_code=201)
def save_review(session_id: str, body: MoveReviewIn, request: Request) -> StoredReview:
    try:
        return jr.save_review(_db(request), session_id, body)
    except tr.SessionNotFound as e:
        raise HTTPException(404, "Không tìm thấy buổi tập.") from e
    except jr.MoveNotFound as e:
        raise HTTPException(404, f"Buổi tập chưa có nước số {body.move_number}.") from e
    except jr.ReviewMismatch as e:
        raise HTTPException(400, str(e)) from e


@router.get("/sessions/{session_id}/reviews")
def list_reviews(session_id: str, request: Request) -> list[StoredReview]:
    try:
        return jr.list_reviews(_db(request), session_id)
    except tr.SessionNotFound as e:
        raise HTTPException(404, "Không tìm thấy buổi tập.") from e


@router.get("/journal/mistakes")
def mistakes(
    request: Request,
    component: Component | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return jr.list_mistakes(_db(request), component, date_from, date_to, limit, offset)


@router.get("/journal/patterns")
def patterns(request: Request) -> dict[str, Any]:
    return jr.patterns(_db(request))


@router.get("/stats/summary")
def summary(request: Request) -> dict[str, Any]:
    return jr.summary(_db(request))
