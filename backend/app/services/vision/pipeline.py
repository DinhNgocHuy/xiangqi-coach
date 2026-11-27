"""Screenshot -> board: locate -> canonical grid -> classify -> orient -> rules check.

Never guesses silently: squares below CONFIDENCE_THRESHOLD are listed as uncertain, and a placement
(fen_placement) is only returned when nothing is uncertain and the rules adapter accepts the position.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from app.services.rules.xiangqi import board_to_fen, validate_position
from app.services.vision import orient
from app.services.vision.classify import Theme, classify
from app.services.vision.grid import Grid
from app.services.vision.locate import locate_board

CONFIDENCE_THRESHOLD = 0.5


@dataclass
class BoardResult:
    board: list[list[str | None]]  # board[rank][file], our convention (rank 0 = Red back rank)
    confidence: list[list[float]]  # same indexing
    orientation: orient.Orientation | None
    fen_placement: str | None  # FEN piece-placement field; side to move cannot be seen in a screenshot
    grid: Grid
    low_confidence: list[str] = field(default_factory=list)  # squares like "e0"
    problems: list[str] = field(default_factory=list)
    timing_ms: float = 0.0


def recognize(image: np.ndarray, theme: Theme, t0: float | None = None) -> BoardResult:
    """Raises locate.BoardNotFoundError when there is no board in the image.

    t0: perf_counter() when the request started (so timing_ms includes decoding); default now.
    """
    t0 = time.perf_counter() if t0 is None else t0
    grid = locate_board(image)
    labels, conf = classify(grid.canonical(image), theme)
    problems: list[str] = []
    # A point whose surroundings are cut off by the image edge was classified on padding: never trust it.
    pts, half = grid.points(), grid.cell / 2
    h, w = image.shape[:2]
    outside = (pts[..., 0] - half < 0) | (pts[..., 0] + half > w) | (pts[..., 1] - half < 0) | (pts[..., 1] + half > h)
    if outside.any():
        conf = np.where(outside, 0.0, conf)
        problems.append("board is cut off by the image edge")
    orientation = orient.detect(labels)
    if orientation is None:
        problems.append("orientation unknown: no king found in a palace (assumed red at bottom)")
    board = orient.to_board(labels, orientation or "red_bottom")
    confidence = [[round(float(c), 3) for c in row] for row in orient.to_board(conf.tolist(), orientation or "red_bottom")]
    low = [
        orient.square_name(r, f)
        for r in range(10)
        for f in range(9)
        if confidence[r][f] < CONFIDENCE_THRESHOLD
    ]
    if low:
        problems.append(f"{len(low)} uncertain square(s): {', '.join(low)}")
    problems += validate_position(board)
    fen_placement = None
    if not problems:
        fen_placement = board_to_fen(board).split()[0]
    return BoardResult(
        board=board,
        confidence=confidence,
        orientation=orientation,
        fen_placement=fen_placement,
        grid=grid,
        low_confidence=low,
        problems=problems,
        timing_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
