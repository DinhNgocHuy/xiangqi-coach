from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["w", "b"]


class SessionCreate(BaseModel):
    start_fen: str | None = Field(default=None, max_length=200)  # full FEN incl. side to move; default = start
    note: str | None = Field(default=None, max_length=2000)


class PositionIn(BaseModel):
    """A placement the user/vision has CONFIRMED. Exactly one of the two fields."""

    placement: list[list[str | None]] | None = Field(default=None, max_length=10)  # board[rank][file], rank 0 = Red
    fen_placement: str | None = Field(default=None, max_length=100)  # FEN board field; extra fields ignored


class MoveIn(BaseModel):
    uci: str = Field(max_length=5)


class MoveOut(BaseModel):
    move_number: int  # ply index, 1-based
    side: Side
    uci: str
    fen_before: str
    fen_after: str
    created_at: str


class SessionSummary(BaseModel):
    id: str
    started_at: str
    ended_at: str | None
    note: str | None
    start_fen: str
    fen: str
    side_to_move: Side
    status: Literal["active", "ended", "checkmate", "stalemate"]  # checkmate/stalemate: side_to_move lost
    move_count: int


class SessionDetail(SessionSummary):
    moves: list[MoveOut]


class PositionResult(BaseModel):
    result: Literal["recorded", "unchanged", "inconsistent"]
    move: MoveOut | None = None
    reason: str | None = None
    suggestion: list[str] | None = None  # 2-move line to confirm via POST /moves, never auto-recorded
    session: SessionSummary
