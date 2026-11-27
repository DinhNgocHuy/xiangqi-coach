"""SYNTHETIC screenshots for vision tests. These are NOT Ziga images.

No real, labelled Ziga screenshots exist yet, so the tests render boards with OpenCV: wood-like board,
grid lines, river text, palace diagonals, outer frame, pieces as cream discs with a dark rim, a coloured
inner ring and a Latin letter (OpenCV cannot draw CJK; red and black use the SAME letter, so colour has
to come from the colour feature). The board sits at a random scale/offset inside a "browser" canvas with
UI clutter, optional last-move highlights, blur and JPEG noise, in either orientation.
Passing tests here proves the algorithm and plumbing, not accuracy on Ziga.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.services.rules.xiangqi import START_FEN, apply_move, legal_moves, parse_fen

RED, BLACK = (40, 40, 200), (35, 35, 35)  # BGR ink
FACE, RIM, LINE, WOOD = (185, 222, 240), (50, 80, 110), (45, 70, 100), (120, 175, 215)


@dataclass
class Synth:
    image: np.ndarray  # BGR
    points: np.ndarray  # (10, 9, 2) true (x, y) per [image row][image col]
    cell: float
    board: tuple  # truth, our convention board[rank][file]
    red_bottom: bool


def random_board(rng: np.random.Generator, plies: int) -> tuple:
    """Placement after `plies` random legal moves from the start (stops early at mate/stalemate)."""
    fen = START_FEN
    for _ in range(plies):
        moves = legal_moves(fen)
        if not moves:
            break
        fen = apply_move(fen, moves[rng.integers(len(moves))])
    return parse_fen(fen).board


def _image_cell(rank: int, file: int, red_bottom: bool) -> tuple[int, int]:
    return (9 - rank, file) if red_bottom else (rank, 8 - file)


def _clutter(canvas: np.ndarray, rng: np.random.Generator, keep_out: tuple[int, int, int, int]) -> None:
    h, w = canvas.shape[:2]
    cv2.rectangle(canvas, (0, 0), (w, 56), (70, 70, 70), -1)  # browser toolbar
    cv2.rectangle(canvas, (120, 12), (w - 120, 44), (245, 245, 245), -1)  # address bar
    cv2.putText(canvas, "https://ziga.vn/ (synthetic)", (130, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 1)
    kx, ky, kw, kh = keep_out
    for _ in range(int(rng.integers(6, 14))):
        rw, rh = int(rng.integers(40, 300)), int(rng.integers(20, 200))
        x, y = int(rng.integers(0, max(1, w - rw))), int(rng.integers(60, max(61, h - rh)))
        if x < kx + kw + 12 and x + rw > kx - 12 and y < ky + kh + 12 and y + rh > ky - 12:
            continue
        color = tuple(int(c) for c in rng.integers(0, 256, 3))
        cv2.rectangle(canvas, (x, y), (x + rw, y + rh), color, -1)
        cv2.rectangle(canvas, (x, y), (x + rw, y + rh), (90, 90, 90), 1)
        if rh > 25:
            cv2.putText(canvas, "Player 1500", (x + 4, y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1)


def _piece(img: np.ndarray, x: int, y: int, r: int, piece: str, d: float) -> None:
    ink = RED if piece.isupper() else BLACK
    cv2.circle(img, (x + 2, y + 2), r, (80, 110, 140), -1, cv2.LINE_AA)  # shadow
    cv2.circle(img, (x, y), r, FACE, -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), r, RIM, max(1, round(d / 30)), cv2.LINE_AA)
    cv2.circle(img, (x, y), int(r * 0.84), ink, max(1, round(d / 45)), cv2.LINE_AA)
    letter, font, thick = piece.upper(), cv2.FONT_HERSHEY_DUPLEX, max(1, round(d / 22))
    scale = cv2.getFontScaleFromHeight(font, int(r * 0.9), thick)
    (tw, th), _ = cv2.getTextSize(letter, font, scale, thick)
    cv2.putText(img, letter, (x - tw // 2, y + th // 2), font, scale, ink, thick, cv2.LINE_AA)


def render(
    board: tuple,
    rng: np.random.Generator,
    *,
    red_bottom: bool = True,
    board_width: int | None = None,
    highlight: bool | None = None,
    noise: bool = True,
) -> Synth:
    bw = int(board_width or rng.integers(400, 901))
    d = bw / 9.4  # 8 cells + 0.7 cell margin each side
    bh = int(round(d * 10.4))
    cw, ch = bw + int(rng.integers(150, 700)), bh + int(rng.integers(130, 400))
    canvas = np.full((ch, cw, 3), 236, np.uint8)
    ox, oy = int(rng.integers(10, cw - bw - 10)), int(rng.integers(66, ch - bh - 10))
    _clutter(canvas, rng, (ox, oy, bw, bh))

    # board: wood colour + low-frequency texture
    tex = cv2.resize(rng.normal(0, 8, (8, 6)).astype(np.float32), (bw, bh), interpolation=cv2.INTER_CUBIC)
    wood = np.clip(np.array(WOOD, np.float32) + tex[..., None], 0, 255).astype(np.uint8)
    canvas[oy : oy + bh, ox : ox + bw] = wood
    xs = [int(round(ox + 0.7 * d + j * d)) for j in range(9)]
    ys = [int(round(oy + 0.7 * d + i * d)) for i in range(10)]
    t = max(1, round(d / 40))
    f = int(round(0.3 * d))
    cv2.rectangle(canvas, (xs[0] - f, ys[0] - f), (xs[-1] + f, ys[-1] + f), LINE, t + 1)  # outer frame
    for y in ys:
        cv2.line(canvas, (xs[0], y), (xs[-1], y), LINE, t)
    for j, x in enumerate(xs):
        if j in (0, 8):
            cv2.line(canvas, (x, ys[0]), (x, ys[-1]), LINE, t)
        else:
            cv2.line(canvas, (x, ys[0]), (x, ys[4]), LINE, t)
            cv2.line(canvas, (x, ys[5]), (x, ys[-1]), LINE, t)
    for top in (0, 7):  # palaces
        cv2.line(canvas, (xs[3], ys[top]), (xs[5], ys[top + 2]), LINE, t, cv2.LINE_AA)
        cv2.line(canvas, (xs[5], ys[top]), (xs[3], ys[top + 2]), LINE, t, cv2.LINE_AA)
    scale = cv2.getFontScaleFromHeight(cv2.FONT_HERSHEY_SIMPLEX, int(d * 0.4), 1)
    cv2.putText(canvas, "RIVER", (xs[1], ys[4] + int(d * 0.7)), cv2.FONT_HERSHEY_SIMPLEX, scale, LINE, t)
    cv2.putText(canvas, "BORDER", (xs[5], ys[4] + int(d * 0.7)), cv2.FONT_HERSHEY_SIMPLEX, scale, LINE, t)

    cells = [(i, j) for i in range(10) for j in range(9)]
    if highlight if highlight is not None else rng.random() < 0.5:
        a, b = (cells[k] for k in rng.choice(90, 2, replace=False))
        overlay = canvas.copy()
        half = int(d * 0.47)
        cv2.rectangle(overlay, (xs[a[1]] - half, ys[a[0]] - half), (xs[a[1]] + half, ys[a[0]] + half), (90, 210, 235), -1)
        canvas = cv2.addWeighted(overlay, 0.4, canvas, 0.6, 0)
    else:
        b = None
    r = int(round(0.44 * d))
    for rank in range(10):
        for file in range(9):
            if board[rank][file]:
                i, j = _image_cell(rank, file, red_bottom)
                _piece(canvas, xs[j], ys[i], r, board[rank][file], d)
    if b is not None:  # selection corners around the moved piece, drawn on top
        half, arm = int(d * 0.5), int(d * 0.15)
        cx, cy = xs[b[1]], ys[b[0]]
        for sx in (-1, 1):
            for sy in (-1, 1):
                px, py = cx + sx * half, cy + sy * half
                cv2.line(canvas, (px, py), (px - sx * arm, py), (0, 170, 0), 2)
                cv2.line(canvas, (px, py), (px, py - sy * arm), (0, 170, 0), 2)
    if noise:
        if rng.random() < 0.5:
            canvas = cv2.GaussianBlur(canvas, (3, 3), 0.7)
        ok, jpg = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(75, 96))])
        canvas = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
    points = np.stack(np.meshgrid(np.array(xs, float), np.array(ys, float)), axis=-1)
    return Synth(canvas, points, d, board, red_bottom)


def start_board() -> tuple:
    return parse_fen(START_FEN).board


def ghost_piece(s: Synth, rng: np.random.Generator) -> tuple[np.ndarray, tuple[int, int]]:
    """Imitate a piece mid-animation: paste a copy of one occupied point 0.45 cell to the right.

    Returns the new image and the (image row, image col) of the affected point.
    """
    img, d = s.image.copy(), s.cell
    occupied = [
        (i, j)
        for i in range(10)
        for j in range(9)
        if s.board[9 - i if s.red_bottom else i][j if s.red_bottom else 8 - j]
    ]
    i, j = occupied[rng.integers(len(occupied))]
    x, y = s.points[i, j].astype(int)
    r, dx = int(0.5 * d), int(0.45 * d)
    img[y - r : y + r, x - r + dx : x + r + dx] = s.image[y - r : y + r, x - r : x + r]
    return img, (i, j)


def _points_where(s: Synth, occupied: bool) -> list[tuple[int, int]]:
    return [
        (i, j)
        for i in range(10)
        for j in range(9)
        if bool(s.board[9 - i if s.red_bottom else i][j if s.red_bottom else 8 - j]) == occupied
    ]


def tint_over_piece(s: Synth, rng: np.random.Generator) -> tuple[np.ndarray, tuple[int, int]]:
    """Last-move highlight drawn ON TOP of a piece: semi-transparent yellow square."""
    i, j = _points_where(s, True)[rng.integers(len(_points_where(s, True)))]
    x, y = s.points[i, j].astype(int)
    half = int(0.48 * s.cell)
    overlay = s.image.copy()
    cv2.rectangle(overlay, (x - half, y - half), (x + half, y + half), (60, 220, 240), -1)
    return cv2.addWeighted(overlay, 0.4, s.image, 0.6, 0), (i, j)


def disc_marker(s: Synth, rng: np.random.Generator, filled: bool) -> tuple[np.ndarray, tuple[int, int]]:
    """Piece-sized marker on an EMPTY point: a ring (from-square marker) or a translucent dot (legal-move dot)."""
    empties = _points_where(s, False)
    i, j = empties[rng.integers(len(empties))]
    x, y = s.points[i, j].astype(int)
    r = int(0.44 * s.cell)
    img = s.image.copy()
    if filled:
        overlay = img.copy()
        cv2.circle(overlay, (x, y), r, (70, 160, 70), -1, cv2.LINE_AA)
        img = cv2.addWeighted(overlay, 0.5, img, 0.5, 0)
    else:
        cv2.circle(img, (x, y), r, (40, 170, 40), max(2, round(s.cell / 25)), cv2.LINE_AA)
    return img, (i, j)


def occlude(s: Synth, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Opaque 'dialog' over part of the board. Returns image and (10, 9) mask of covered points."""
    img = s.image.copy()
    i0, j0 = int(rng.integers(0, 7)), int(rng.integers(0, 6))
    i1, j1 = i0 + int(rng.integers(1, 4)), j0 + int(rng.integers(1, 4))
    pad = 0.6 * s.cell
    (x0, y0), (x1, y1) = s.points[i0, j0] - pad, s.points[i1, j1] + pad
    cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), (250, 250, 250), -1)
    cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), (120, 120, 120), 1)
    cv2.putText(img, "Doi thu xin hoa?", (int(x0) + 8, int(y0) + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1)
    covered = np.zeros((10, 9), bool)
    covered[i0 : i1 + 1, j0 : j1 + 1] = True
    return img, covered
