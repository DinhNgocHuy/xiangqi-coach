"""Board orientation on screen and mapping to our convention (board[rank][file], rank 0 = Red back rank).

red_bottom: image row i, col j -> rank 9 - i, file j.  red_top (board flipped 180 deg): rank i, file 8 - j.
"""

from __future__ import annotations

from typing import Literal

Orientation = Literal["red_bottom", "red_top"]
Labels = list[list[str | None]]  # [image row][image col]


def detect(labels: Labels) -> Orientation | None:
    """From the kings' palaces: red king in the bottom 3 rows -> red_bottom. None if no king tells."""
    for i, row in enumerate(labels):
        for j, sq in enumerate(row):
            if sq in ("K", "k") and 3 <= j <= 5:
                bottom = i >= 7
                if bottom or i <= 2:
                    return "red_bottom" if bottom == (sq == "K") else "red_top"
    return None


def to_board(cells: list[list], orientation: Orientation) -> list[list]:
    """Image-ordered 10x9 cells (labels, confidences, ...) -> board[rank][file]."""
    if orientation == "red_bottom":
        return [list(row) for row in reversed(cells)]
    return [list(reversed(row)) for row in cells]


def from_board(board, orientation: Orientation) -> list[list]:
    """Inverse of to_board (the mapping is its own inverse)."""
    return to_board([list(r) for r in board], orientation)


def square_name(rank: int, file: int) -> str:
    return f"{'abcdefghi'[file]}{rank}"
