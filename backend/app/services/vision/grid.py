"""Axis-aligned 9x10 grid: intersection coordinates and the canonical (fixed-scale) board image.

Screen captures are not perspective-distorted, so a grid is fully described by the top-left
intersection and the spacing in x and y. "Image" rows/cols are as seen on screen (row 0 = top);
mapping to ranks/files depends on orientation (orient.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

ROWS, COLS = 10, 9
CELL = 48  # canonical spacing in px: every later step works at this scale, so themes are scale-free


@dataclass(frozen=True)
class Grid:
    x0: float  # image x of the top-left intersection
    y0: float
    dx: float  # spacing between vertical lines
    dy: float  # spacing between horizontal lines

    @property
    def cell(self) -> float:
        return (self.dx + self.dy) / 2

    def points(self) -> np.ndarray:
        """(10, 9, 2) array of (x, y) image coordinates, indexed [image row][image col]."""
        xs = self.x0 + self.dx * np.arange(COLS)
        ys = self.y0 + self.dy * np.arange(ROWS)
        return np.stack(np.meshgrid(xs, ys), axis=-1)

    def bbox(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the line grid in the image."""
        return (round(self.x0), round(self.y0), round(8 * self.dx), round(9 * self.dy))

    def canonical(self, image: np.ndarray) -> np.ndarray:
        """Board resampled so intersection (row i, col j) lands at ((j + 1) * CELL, (i + 1) * CELL)."""
        w, h = 10 * self.dx, 11 * self.dy  # grid plus one cell of margin on each side
        center = (self.x0 + 4 * self.dx, self.y0 + 4.5 * self.dy)
        patch = cv2.getRectSubPix(image, (round(w), round(h)), center)  # replicates border outside image
        return cv2.resize(patch, (10 * CELL, 11 * CELL), interpolation=cv2.INTER_AREA)


def canonical_centers() -> tuple[np.ndarray, np.ndarray]:
    """(xs, ys) of the 9 columns / 10 rows in the canonical image."""
    return CELL * (1 + np.arange(COLS)), CELL * (1 + np.arange(ROWS))
