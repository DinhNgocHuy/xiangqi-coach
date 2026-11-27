import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request

from app.schemas.session import (
    MoveIn,
    MoveOut,
    PositionIn,
    PositionResult,
    SessionCreate,
    SessionDetail,
    SessionSummary,
)
from app.services import tracker as tr
from app.services.rules import xiangqi as rules

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except tr.SessionNotFound as e:
        raise HTTPException(404, "Không tìm thấy buổi tập.") from e
    except tr.SessionConflict as e:
        raise HTTPException(409, str(e)) from e
    except rules.FenError as e:
        raise HTTPException(400, f"Thế cờ không hợp lệ: {e}") from e
    except rules.IllegalMoveError as e:
        raise HTTPException(400, f"Nước đi không hợp lệ: {e}") from e


def _summary(t: tr.MoveTracker) -> SessionSummary:
    return SessionSummary(
        id=t.id,
        started_at=t.started_at,
        ended_at=t.ended_at,
        note=t.note,
        start_fen=t.start_fen,
        fen=t.fen,
        side_to_move=t.side_to_move,
        status=t.status,
        move_count=len(t.moves),
    )


def _detail(t: tr.MoveTracker) -> SessionDetail:
    return SessionDetail(**_summary(t).model_dump(), moves=t.moves)


# Sync handlers: FastAPI runs them in its threadpool, so pyffish search (2-ply) does not block the event loop.
@router.post("", status_code=201)
def create_session(body: SessionCreate, request: Request) -> SessionDetail:
    with _errors():
        return _detail(tr.create(_db(request), body.start_fen, body.note))


@router.get("")
def list_sessions(request: Request) -> list[SessionSummary]:
    return [_summary(t) for t in tr.list_sessions(_db(request))]


@router.get("/{session_id}")
def get_session(session_id: str, request: Request) -> SessionDetail:
    with _errors():
        return _detail(tr.load(_db(request), session_id))


@router.post("/{session_id}/positions")
def submit_position(session_id: str, body: PositionIn, request: Request) -> PositionResult:
    if (body.placement is None) == (body.fen_placement is None):
        raise HTTPException(400, "Cần đúng một trong hai trường: placement hoặc fen_placement.")
    with _errors():
        board = body.placement if body.placement is not None else rules.parse_fen(body.fen_placement).board
        obs = tr.submit_position(_db(request), session_id, board)
        return PositionResult(
            result=obs.result,
            move=obs.move,
            reason=obs.reason,
            suggestion=obs.suggestion,
            session=_summary(tr.load(_db(request), session_id)),
        )


@router.post("/{session_id}/moves", status_code=201)
def add_move(session_id: str, body: MoveIn, request: Request) -> MoveOut:
    with _errors():
        return MoveOut(**tr.record_move(_db(request), session_id, body.uci))


@router.delete("/{session_id}/moves/last")
def undo_move(session_id: str, request: Request) -> MoveOut:
    with _errors():
        return MoveOut(**tr.undo_last(_db(request), session_id))


@router.post("/{session_id}/end")
def end_session(session_id: str, request: Request) -> SessionDetail:
    with _errors():
        return _detail(tr.end(_db(request), session_id))
