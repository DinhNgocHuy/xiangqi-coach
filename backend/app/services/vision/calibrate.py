"""Learn a piece Theme from one screenshot of the standard start position (no manual labels).

The start position is known, so every square's label follows from the orientation, which the colour
feature decides (the side whose pieces are red). Duplicates (pawns, rooks, ...) are averaged into one
template. The theme is checked by re-classifying the calibration image: every square must come out right.
Only the small templates + a few numbers are stored (.npz), never the screenshot.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np

from app.services.rules.xiangqi import START_FEN, parse_fen
from app.services.vision import orient
from app.services.vision.classify import (
    PIECE_LABELS,
    Theme,
    classify,
    color_scores,
    crop_center,
    ring_scores,
    template_side,
)
from app.services.vision.grid import CELL, COLS, ROWS, Grid
from app.services.vision.locate import locate_board

THEME_VERSION = 2
MIN_CONFIDENCE = 0.5  # same threshold as the pipeline uses for "uncertain"


class CalibrationError(ValueError):
    pass


def _start_labels(orientation: orient.Orientation) -> list[list[str | None]]:
    return orient.from_board(parse_fen(START_FEN).board, orientation)


def _radius(gray: np.ndarray, occupied: np.ndarray) -> float:
    """Radius of the strongest circular edge on the occupied squares (rim or inner ring, whichever is
    most distinct): occupancy and template size only need it to be stable for a theme."""
    radii = np.arange(0.25, 0.52, 0.01) * CELL
    score = np.array([np.median(ring_scores(gray, r, (1, 1))[occupied]) for r in radii])
    return float(radii[int(np.argmax(score))])


def calibrate(image: np.ndarray) -> tuple[Theme, Grid, orient.Orientation]:
    grid = locate_board(image)
    canon = grid.canonical(image)
    gray = cv2.cvtColor(canon, cv2.COLOR_BGR2GRAY)
    occupied = np.array([[sq is not None for sq in row] for row in _start_labels("red_bottom")])
    radius = _radius(gray, occupied)
    ring = ring_scores(gray, radius)
    if ring[occupied].min() <= ring[~occupied].max():
        raise CalibrationError("pieces and empty squares are not separable: is this the start position?")
    color, ink = color_scores(canon, radius)
    red_bottom = color[5:][occupied[5:]].mean() > color[:5][occupied[:5]].mean()
    orientation: orient.Orientation = "red_bottom" if red_bottom else "red_top"
    labels = _start_labels(orientation)
    is_red = np.array([[bool(sq and sq.isupper()) for sq in row] for row in labels])
    is_black = occupied & ~is_red
    if color[is_red].min() <= color[is_black].max():
        raise CalibrationError("red and black pieces are not separable by colour")

    side = template_side(radius)
    crops: dict[str, list[np.ndarray]] = {p: [] for p in PIECE_LABELS}
    for i in range(ROWS):
        for j in range(COLS):
            if labels[i][j]:
                crops[labels[i][j]].append(crop_center(gray, i, j, side).astype(np.float32))
    theme = Theme(
        templates=np.stack([np.mean(crops[p], axis=0) for p in PIECE_LABELS]).astype(np.float32),
        radius=radius,
        ring_empty=float(np.median(ring[~occupied])),
        ring_piece=float(np.median(ring[occupied])),
        color_red=float(np.median(color[is_red])),
        color_black=float(np.median(color[is_black])),
        ink_min=float(ink[occupied].min()) / 2,
    )
    got, conf = classify(canon, theme)
    if got != labels or conf.min() < MIN_CONFIDENCE:
        raise CalibrationError("calibration self-check failed: pieces could not be told apart reliably")
    return theme, grid, orientation


def save_theme(theme: Theme, path: Path) -> None:
    """Atomic write (unique temp file in the same dir, fsync, rename). Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            np.savez(f, version=THEME_VERSION, templates=theme.templates, scalars=np.array(_scalars(theme)))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _scalars(theme: Theme) -> list[float]:
    return [theme.radius, theme.ring_empty, theme.ring_piece, theme.color_red, theme.color_black, theme.ink_min]


def load_theme(path: Path) -> Theme | None:
    """None if there is no theme yet; ValueError if the file is unreadable, old or malformed."""
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            version = int(data["version"])
            templates, scalars = data["templates"].astype(np.float32), data["scalars"].astype(float)
    except (OSError, EOFError, KeyError, ValueError, TypeError, zipfile.BadZipFile) as e:
        raise ValueError(f"theme file unreadable: {e}") from e
    if version != THEME_VERSION:
        raise ValueError("theme file has an unsupported version")
    n_scalars = len(Theme.__dataclass_fields__) - 1
    if (
        templates.ndim != 3
        or templates.shape[0] != len(PIECE_LABELS)
        or templates.shape[1] != templates.shape[2]
        or not 5 <= templates.shape[1] <= CELL
        or templates.shape[1] % 2 == 0
        or scalars.shape != (n_scalars,)
        or not (np.isfinite(templates).all() and np.isfinite(scalars).all())
    ):
        raise ValueError("theme file is malformed")
    radius, ring_empty, ring_piece, color_red, color_black, ink_min = (float(v) for v in scalars)
    if not (0 < radius <= CELL / 2 and 0 <= ring_empty < ring_piece and color_black < color_red and ink_min >= 0):
        raise ValueError("theme file has implausible values")
    if template_side(radius) != templates.shape[1]:
        raise ValueError("theme file is malformed")
    return Theme(templates, radius, ring_empty, ring_piece, color_red, color_black, ink_min)
