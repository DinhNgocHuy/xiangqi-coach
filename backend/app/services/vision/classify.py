"""Per-intersection classification on the canonical board image (grid.CELL px per cell).

- Occupancy: a piece is a disc, so its rim gives a strong *radial* gradient all around a circle of the
  disc radius. Grid lines and palace diagonals cross that circle radially, so their gradient is tangential
  and barely counts. Score = 30th percentile over 48 angles of max |radial gradient| in a radius band.
- Empty needs positive evidence too: every grid arm expected at that point (none outward at edges, none
  across the river on inner files) must show dark strokes. Anything covering the point (dialog, toast,
  cursor, off-image padding) therefore makes the square uncertain instead of "empty".
- Colour: share of red-hue pixels among ink (red, or much darker than the disc face) pixels inside the disc;
  too little ink (e.g. a marker ring, a heavy tint) -> no colour confidence.
- Type: normalised cross-correlation (+-2 px shift) of the grayscale disc centre against the Theme's
  7 templates of that colour.
Every decision gets a 0..1 confidence; the square's confidence is the weakest of its decisions.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.services.vision.grid import CELL, COLS, ROWS, canonical_centers

PIECE_LABELS = "KABNRCPkabnrcp"  # template order; uppercase = Red
N_ANGLES = 48
SHIFT = 2  # px tolerance of template position (canonical scale)
TEMPLATE_FACTOR = 1.2  # template side = 1.2 * disc radius (inside the inner ring)

# Confidence ramps: a decision is fully confident when its evidence clears these margins.
OCC_MARGIN = 0.3  # occupancy score distance from 0.5 (0 = typical empty, 1 = typical piece)
COLOR_MARGIN = 0.25  # colour score distance from 0.5
# NCC best minus second best of the same colour, as a fraction of how different those two templates are
# (1 - NCC between them): look-alike pieces of a theme cannot be expected to differ by a fixed amount.
TYPE_MARGIN_FRACTION = 0.5
MIN_TEMPLATE_GAP = 0.1  # floor, so near-identical templates never yield confident calls
TYPE_MIN = 0.8  # best-template NCC at or below this -> no confidence (a piece mid-animation scores 0.6-0.78)
ARM_MIN, ARM_FULL = 0.3, 0.7  # stroke coverage of the weakest expected arm: no / full "empty" confidence
ARM_SPAN = (0.15, 0.38)  # arm part checked, in cells from the point (neighbour discs start at ~0.5)
INK_DARK = 0.6  # ink = pixel value below 0.6 x the disc's median value (relative, survives tints)
TYPE_FULL = 0.9  # ... at or above this -> fully confident (clean synthetic matches score 0.95-0.99)


@dataclass(frozen=True)
class Theme:
    """Piece appearance learned by calibration (calibrate.py). All sizes in canonical px."""

    templates: np.ndarray  # (14, T, T) float32 grayscale, order PIECE_LABELS
    radius: float  # disc radius
    ring_empty: float  # typical occupancy evidence of an empty intersection
    ring_piece: float  # ... of a piece
    color_red: float  # typical colour score of red pieces
    color_black: float
    ink_min: float  # fewest ink pixels a piece may show (half the calibration minimum)


@dataclass
class Features:
    ring: np.ndarray  # (10, 9)
    color: np.ndarray  # (10, 9)
    ink: np.ndarray  # (10, 9) ink pixel count inside the disc centre


def template_side(radius: float) -> int:
    return int(round(TEMPLATE_FACTOR * radius)) | 1  # odd, so it centres on the intersection


def ring_scores(gray: np.ndarray, radius: float, band: tuple[float, float] = (0.85, 1.15)) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    xs, ys = canonical_centers()
    theta = np.linspace(0, 2 * np.pi, N_ANGLES, endpoint=False, dtype=np.float32)
    radii = radius * np.linspace(band[0], band[1], 7 if band[1] > band[0] else 1, dtype=np.float32)
    radii = np.minimum(radii, CELL / 2 - 1)  # never reach the rim of a piece on the neighbouring point
    cos, sin = np.cos(theta), np.sin(theta)
    # sample map: (squares * radii, angles)
    cx = np.repeat(np.tile(xs, ROWS), len(radii)).astype(np.float32)[:, None]
    cy = np.repeat(np.repeat(ys, COLS), len(radii)).astype(np.float32)[:, None]
    rr = np.tile(radii, ROWS * COLS)[:, None]
    mapx, mapy = (cx + rr * cos).astype(np.float32), (cy + rr * sin).astype(np.float32)
    sx = cv2.remap(gx, mapx, mapy, cv2.INTER_LINEAR)
    sy = cv2.remap(gy, mapx, mapy, cv2.INTER_LINEAR)
    radial = np.abs(sx * cos + sy * sin).reshape(ROWS * COLS, len(radii), N_ANGLES).max(axis=1)
    return np.percentile(radial, 30, axis=1).reshape(ROWS, COLS)


def color_scores(bgr: np.ndarray, radius: float) -> tuple[np.ndarray, np.ndarray]:
    """(colour score, ink pixel count) per point."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    red = ((h <= 10) | (h >= 170)) & (s >= 90) & (v >= 70)
    half = template_side(radius) // 2
    xs, ys = canonical_centers()
    color, ink = np.zeros((ROWS, COLS)), np.zeros((ROWS, COLS))
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            win = np.s_[y - half : y + half + 1, x - half : x + half + 1]
            pr, pv = red[win], v[win]
            r = int(pr.sum())
            k = int(((pv < INK_DARK * np.median(pv)) & ~pr).sum())
            color[i, j], ink[i, j] = r / (r + k + 1), r + k
    return color, ink


def expected_arms(i: int, j: int) -> list[tuple[int, int]]:
    """Directions (dx, dy) in which grid lines leave image point (row i, col j). Same for both orientations."""
    arms = []
    if j > 0:
        arms.append((-1, 0))
    if j < COLS - 1:
        arms.append((1, 0))
    if i > 0 and not (i == 5 and 0 < j < COLS - 1):  # inner files stop at the river
        arms.append((0, -1))
    if i < ROWS - 1 and not (i == 4 and 0 < j < COLS - 1):
        arms.append((0, 1))
    return arms


def arm_scores(gray: np.ndarray) -> np.ndarray:
    """Stroke coverage of the weakest expected arm at each point (1 = all grid lines visible)."""
    strokes = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 8) > 0
    strokes = cv2.dilate(strokes.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0  # +-2 px across the line
    xs, ys = canonical_centers()
    steps = np.arange(int(ARM_SPAN[0] * CELL), int(ARM_SPAN[1] * CELL) + 1)
    out = np.zeros((ROWS, COLS))
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            out[i, j] = min(float(strokes[y + dy * steps, x + dx * steps].mean()) for dx, dy in expected_arms(i, j))
    return out


def features(bgr: np.ndarray, radius: float) -> Features:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return Features(ring_scores(gray, radius), *color_scores(bgr, radius))


def crop_center(gray: np.ndarray, i: int, j: int, side: int, pad: int = 0) -> np.ndarray:
    xs, ys = canonical_centers()
    half = side // 2 + pad
    return gray[ys[i] - half : ys[i] + half + 1, xs[j] - half : xs[j] + half + 1]


def template_gaps(templates: np.ndarray) -> np.ndarray:
    """(14, 14) 1 - NCC between templates, floored at MIN_TEMPLATE_GAP."""
    n = len(templates)
    sim = np.array([[cv2.matchTemplate(templates[a], templates[b], cv2.TM_CCOEFF_NORMED)[0, 0] for b in range(n)] for a in range(n)])
    return np.maximum(1 - sim, MIN_TEMPLATE_GAP)


def classify(bgr: np.ndarray, theme: Theme) -> tuple[list[list[str | None]], np.ndarray]:
    """Labels [image row][image col] (piece letter or None) and confidences (10, 9) for a canonical image."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    feats = features(bgr, theme.radius)
    side = theme.templates.shape[1]
    gaps = template_gaps(theme.templates)
    # log scale: rim contrast varies a lot with blur/scale, the empty/piece gap is a ratio
    lo, hi = np.log1p(theme.ring_empty), np.log1p(theme.ring_piece)
    occ = (np.log1p(feats.ring) - lo) / max(hi - lo, 1e-6)
    col = (feats.color - theme.color_black) / max(theme.color_red - theme.color_black, 1e-6)
    labels: list[list[str | None]] = [[None] * COLS for _ in range(ROWS)]
    conf = np.clip(np.abs(occ - 0.5) / OCC_MARGIN, 0, 1)
    empty_ok = np.clip((arm_scores(gray) - ARM_MIN) / (ARM_FULL - ARM_MIN), 0, 1)
    conf = np.where(occ < 0.5, np.minimum(conf, empty_ok), conf)
    for i in range(ROWS):
        for j in range(COLS):
            if occ[i, j] < 0.5:
                continue
            red = col[i, j] >= 0.5
            patch = crop_center(gray, i, j, side, SHIFT).astype(np.float32)
            offset = 0 if red else 7
            scores = sorted(
                (float(cv2.matchTemplate(patch, theme.templates[offset + t], cv2.TM_CCOEFF_NORMED).max()), t)
                for t in range(7)
            )
            (second, t2), (best, t) = scores[-2], scores[-1]
            expected = TYPE_MARGIN_FRACTION * gaps[offset + t, offset + t2]
            labels[i][j] = PIECE_LABELS[offset + t]
            conf[i, j] = min(
                conf[i, j],
                np.clip(abs(col[i, j] - 0.5) / COLOR_MARGIN, 0, 1) if feats.ink[i, j] >= theme.ink_min else 0.0,
                np.clip((best - second) / expected, 0, 1),
                np.clip((best - TYPE_MIN) / (TYPE_FULL - TYPE_MIN), 0, 1),
            )
    return labels, conf
