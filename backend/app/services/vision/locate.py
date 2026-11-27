"""Find the Xiangqi line grid (9 vertical x 10 horizontal lines) in a screenshot.

1. Dark thin strokes: adaptive threshold (lines are darker than their neighbourhood).
2. Long horizontal / vertical strokes: morphological opening with 1-D kernels (drops glyphs, discs, diagonals).
3. Candidate regions: connected components of both stroke masks (the grid is one connected net).
4. Per candidate: best arithmetic progression of 10 rows / 9 columns in the stroke profiles,
   refined by least squares on line centroids, then checked for line coverage and square-ish cells.
The candidate with the best coverage wins; none -> BoardNotFoundError.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.services.vision.grid import COLS, ROWS, Grid

MIN_CELL = 18.0  # px; smaller boards are not readable anyway
KERNEL = 15  # min straight stroke length in px kept as a "line"
MIN_LINE_COVERAGE = 0.3  # a grid line counts as seen when >= 30% of its length is a stroke
MIN_LINES_SEEN = 0.6  # ... and >= 60% of the lines of each direction are seen
MAX_ASPECT = 1.25  # dx/dy of a board cell
RIVER_WEIGHT = 2.0  # per line crossing (or not crossing) the river where it should not (should)


class BoardNotFoundError(ValueError):
    pass


def stroke_masks(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (KERNEL, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, KERNEL)))
    return horiz, vert


def _progression(profile: np.ndarray, n: int, d_min: float, d_max: float) -> tuple[float, float, float]:
    """Best (start, step, score) of n equally spaced peaks in a 0..1 coverage profile."""
    length = len(profile)
    p = np.minimum(profile, 1.0)
    p = np.maximum(p, np.maximum(np.r_[0, p[:-1]], np.r_[p[1:], 0]))  # tolerate +-1 px
    k = np.arange(n)
    best = (0.0, 0.0, -1.0)
    for d in np.arange(d_min, d_max, 0.5):
        starts = np.arange(0, int(length - d * (n - 1)))
        if not len(starts):
            break
        scores = p[np.rint(starts[:, None] + k * d).astype(int)].sum(axis=1)
        i = int(np.argmax(scores))
        if scores[i] > best[2]:
            best = (float(starts[i]), float(d), float(scores[i]))
    return best


def _refine(profile: np.ndarray, start: float, step: float, n: int) -> tuple[float, float]:
    """Least-squares fit of line centroids near the predicted positions; occluded lines are skipped."""
    ks, pos = [], []
    w = max(3, int(step / 8))  # progression is good to ~3 px; wider windows grab a nearby frame line
    for k in range(n):
        c = int(round(start + k * step))
        lo, hi = max(0, c - w), min(len(profile), c + w + 1)
        seg = profile[lo:hi]
        if seg.max() < MIN_LINE_COVERAGE:
            continue
        weights = np.where(seg >= seg.max() / 2, seg, 0)
        ks.append(k)
        pos.append(lo + float((weights * np.arange(len(seg))).sum() / weights.sum()))
    if len(ks) < 3:
        return start, step
    step, start = np.polyfit(ks, pos, 1)
    return float(start), float(step)


def _coverage(mask: np.ndarray, positions: np.ndarray, lo: float, hi: float, axis: int) -> np.ndarray:
    """Fraction of each line (row if axis=0, column if axis=1) between lo..hi covered by strokes (+-1 px)."""
    out = []
    size_along, size_across = (mask.shape[1], mask.shape[0]) if axis == 0 else (mask.shape[0], mask.shape[1])
    a, b = max(0, int(round(lo))), min(size_along, int(round(hi)) + 1)  # clamp: negative slices wrap around
    for p in positions:
        c = int(round(p))
        if not 0 <= c < size_across or a >= b:
            out.append(0.0)  # line outside the image: no evidence
            continue
        if axis == 0:
            band = mask[max(0, c - 1) : c + 2, a:b]
            out.append(float((band.max(axis=0) > 0).mean()) if band.size else 0.0)
        else:
            band = mask[a:b, max(0, c - 1) : c + 2]
            out.append(float((band.max(axis=1) > 0).mean()) if band.size else 0.0)
    return np.array(out)


def _fit(horiz: np.ndarray, vert: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[Grid, float] | None:
    hroi, vroi = horiz[y : y + h, x : x + w] > 0, vert[y : y + h, x : x + w] > 0
    rows_profile, cols_profile = hroi.mean(axis=1), vroi.mean(axis=0)
    y0, dy, _ = _progression(rows_profile, ROWS, MIN_CELL, h / (ROWS - 1))
    x0, dx, _ = _progression(cols_profile, COLS, MIN_CELL, w / (COLS - 1))
    if dx <= 0 or dy <= 0:
        return None
    y0, dy = _refine(rows_profile, y0, dy, ROWS)
    x0, dx = _refine(cols_profile, x0, dx, COLS)
    if not (1 / MAX_ASPECT <= dx / dy <= MAX_ASPECT) or min(dx, dy) < MIN_CELL:
        return None
    # A strong stray line outside the grid (toolbar, panel edge) can win the progression search, and the
    # search box (component widened by 1/8 per side) allows it to be off by <= ~2.5 cells. The true grid is the
    # shift whose lines are best covered *within* the grid span and do not continue past it. Rows and
    # columns are searched one after the other (14 evaluations instead of 49) to stay within the time budget.
    # The river anchors the absolute position: only the two edge files cross it. Without this a board whose
    # first rank/file is cut off by the image edge fits equally well one cell shifted.
    def evaluate(sx: int, sy: int) -> tuple[Grid, float, float]:
        grid = Grid(x + x0 + sx * dx, y + y0 + sy * dy, dx, dy)
        ys, xs = grid.y0 + dy * np.arange(ROWS), grid.x0 + dx * np.arange(COLS)
        hcov = _coverage(horiz, ys, xs[0], xs[-1], axis=0)
        vcov = _coverage(vert, xs, ys[0], ys[-1], axis=1)
        m = 3
        hout = _coverage(horiz, ys, xs[0] - dx, xs[0] - m, 0) + _coverage(horiz, ys, xs[-1] + m, xs[-1] + dx, 0)
        vout = _coverage(vert, xs, ys[0] - dy, ys[0] - m, 1) + _coverage(vert, xs, ys[-1] + m, ys[-1] + dy, 1)
        river = _coverage(vert, xs, ys[4] + 0.15 * dy, ys[5] - 0.15 * dy, 1)
        river_score = RIVER_WEIGHT * (river[[0, -1]].sum() - river[1:-1].sum())
        seen = min((hcov >= MIN_LINE_COVERAGE).mean(), (vcov >= MIN_LINE_COVERAGE).mean())
        return grid, float(hcov.sum() + vcov.sum() - hout.sum() - vout.sum() + river_score), float(seen)

    shifts = range(-3, 4)
    sx = sy = 0
    for _ in range(2):  # rows then columns, twice: the first row pick may have used shifted columns
        sy = max(shifts, key=lambda k: evaluate(sx, k)[1])
        sx = max(shifts, key=lambda k: evaluate(k, sy)[1])
    grid, score, seen = evaluate(sx, sy)
    return (grid, score) if seen >= MIN_LINES_SEEN else None


def locate_board(image: np.ndarray) -> Grid:
    """Grid of the board in a BGR screenshot. Raises BoardNotFoundError."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    horiz, vert = stroke_masks(gray)
    net = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(net, connectivity=8)
    best: tuple[Grid, float] | None = None
    for x, y, w, h, _area in stats[1:n]:
        if w < 7 * MIN_CELL or h < 8 * MIN_CELL:
            continue
        # Lines fully hidden by pieces (start position back ranks) may lie outside the component: widen the box.
        mx, my = w // 8, h // 8
        x0, y0 = max(0, x - mx), max(0, y - my)
        x1, y1 = min(gray.shape[1], x + w + mx), min(gray.shape[0], y + h + my)
        fit = _fit(horiz, vert, int(x0), int(y0), int(x1 - x0), int(y1 - y0))
        if fit and (best is None or fit[1] > best[1]):
            best = fit
    if best is None:
        raise BoardNotFoundError("board not found")
    return best[0]
