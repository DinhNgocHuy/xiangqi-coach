from typing import Literal

from pydantic import BaseModel

Orientation = Literal["red_bottom", "red_top"]


class GridOut(BaseModel):
    """Where the board's line grid is in the submitted image (px)."""

    x: int
    y: int
    width: int
    height: int
    cell: float


class BoardResult(BaseModel):
    board: list[list[str | None]]  # board[rank][file], rank 0 = Red back rank; uppercase = Red
    confidence: list[list[float]]  # 0..1, same indexing
    orientation: Orientation | None  # None = no king seen in a palace (board assumed red_bottom)
    fen_placement: str | None  # only when no square is uncertain and the position passes the rules check
    side_to_move: None = None  # not visible in a screenshot; the caller decides
    low_confidence: list[str]  # squares like "e0" below the confidence threshold
    problems: list[str]
    grid: GridOut
    timing_ms: float


class CalibrateResult(BaseModel):
    orientation: Orientation
    disc_radius_px: float  # in the submitted image
    grid: GridOut
