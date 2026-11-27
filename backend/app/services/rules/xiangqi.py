"""Xiangqi rules: thin adapter over pyffish (Fairy-Stockfish, GPL-3.0).

Move generation, check and mate come from pyffish. This module owns:
- FEN <-> board matrix (used by vision / move tracker),
- coordinate conversion: our UCI (Pikafish style) uses ranks 0-9 ("a0a1"),
  pyffish uses ranks 1-10 ("a1a2", "a10a9"); files a-i are the same,
- domain sanity checks pyffish does not enforce (palace, elephant points, pawn squares, counts).

Board matrix: board[rank][file], rank 0 = Red back rank, file 0 = 'a'. Uppercase = Red ('w'),
lowercase = Black ('b'), None = empty. Pieces K A B N R C P; 'E'/'H' accepted as aliases of B/N.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

import pyffish as sf

VARIANT = "xiangqi"
FILES = "abcdefghi"
RANKS = 10
START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

Side = Literal["w", "b"]
Square = str | None
Board = tuple[tuple[Square, ...], ...]
GameStatus = Literal["checkmate", "stalemate"]

PIECES = frozenset("KABNRCPkabnrcp")
ALIASES = {"E": "B", "H": "N", "e": "b", "h": "n"}
MAX_COUNT = {"K": 1, "A": 2, "B": 2, "N": 2, "R": 2, "C": 2, "P": 5}

# (file, rank) points for Red; Black's are mirrored with rank -> 9 - rank.
_RED_PALACE = {(f, r) for f in (3, 4, 5) for r in (0, 1, 2)}
_RED_ADVISOR = {(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)}
_RED_ELEPHANT = {(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)}

_UCI_RE = re.compile(r"^([a-i])(\d)([a-i])(\d)$")
_SF_RE = re.compile(r"^([a-i])(\d{1,2})([a-i])(\d{1,2})$")


class FenError(ValueError):
    """FEN is malformed or describes a position the rules engine cannot play from."""


class IllegalMoveError(ValueError):
    pass


@dataclass(frozen=True)
class Position:
    board: Board
    side: Side
    halfmove: int = 0
    fullmove: int = 1


# ---------------------------------------------------------------- coordinates


def to_engine_move(uci: str) -> str:
    """Our UCI (ranks 0-9) -> pyffish (ranks 1-10)."""
    m = _UCI_RE.match(uci)
    if not m:
        raise IllegalMoveError(f"malformed move {uci!r}")
    f1, r1, f2, r2 = m.groups()
    return f"{f1}{int(r1) + 1}{f2}{int(r2) + 1}"


def from_engine_move(move: str) -> str:
    """pyffish (ranks 1-10) -> our UCI (ranks 0-9)."""
    m = _SF_RE.match(move)
    if not m or not (1 <= int(m[2]) <= 10 and 1 <= int(m[4]) <= 10):
        raise ValueError(f"unexpected pyffish move {move!r}")
    f1, r1, f2, r2 = m.groups()
    return f"{f1}{int(r1) - 1}{f2}{int(r2) - 1}"


# ---------------------------------------------------------------- FEN


def _normalize_piece(ch: str) -> str:
    ch = ALIASES.get(ch, ch)
    if ch not in PIECES:
        raise FenError(f"invalid piece {ch!r}")
    return ch


def normalize_board(board: Sequence[Sequence[str | None]]) -> Board:
    """Validate shape (10x9) and piece letters; map aliases; '' / '.' -> None."""
    if len(board) != RANKS or any(len(row) != 9 for row in board):
        raise FenError("board must be 10 ranks x 9 files")
    return tuple(
        tuple(None if sq in (None, "", ".") else _normalize_piece(sq) for sq in row) for row in board
    )


def parse_fen(fen: str) -> Position:
    parts = fen.strip().split()
    if not parts:
        raise FenError("empty FEN")
    rows = parts[0].split("/")
    if len(rows) != RANKS:
        raise FenError(f"expected 10 ranks, got {len(rows)}")
    board: list[tuple[Square, ...]] = []
    for row in reversed(rows):  # first FEN row is rank 9
        squares: list[Square] = []
        for ch in row:
            if ch.isdigit():
                squares.extend([None] * int(ch))
            else:
                squares.append(_normalize_piece(ch))
        if len(squares) != 9:
            raise FenError(f"rank {row!r} does not have 9 files")
        board.append(tuple(squares))
    side = parts[1] if len(parts) > 1 else "w"
    if side not in ("w", "b"):
        raise FenError(f"side to move must be 'w' or 'b', got {side!r}")
    try:
        halfmove = int(parts[4]) if len(parts) > 4 else 0
        fullmove = int(parts[5]) if len(parts) > 5 else 1
    except ValueError:
        raise FenError("move counters must be integers") from None
    return Position(tuple(board), side, halfmove, fullmove)  # type: ignore[arg-type]


def to_fen(pos: Position) -> str:
    rows = []
    for rank in reversed(pos.board):
        out, empty = "", 0
        for sq in rank:
            if sq is None:
                empty += 1
            else:
                out += (str(empty) if empty else "") + sq
                empty = 0
        rows.append(out + (str(empty) if empty else ""))
    return f"{'/'.join(rows)} {pos.side} - - {pos.halfmove} {pos.fullmove}"


def board_to_fen(board: Sequence[Sequence[str | None]], side: Side = "w") -> str:
    return to_fen(Position(normalize_board(board), side))


# ---------------------------------------------------------------- validation


def _side_of(piece: str) -> Side:
    return "w" if piece.isupper() else "b"


def _own(points: set[tuple[int, int]], side: Side) -> set[tuple[int, int]]:
    return points if side == "w" else {(f, 9 - r) for f, r in points}


def _kings_facing(board: Board) -> bool:
    kings = {sq: (f, r) for r, row in enumerate(board) for f, sq in enumerate(row) if sq in ("K", "k")}
    if len(kings) != 2 or kings["K"][0] != kings["k"][0]:
        return False
    file, lo, hi = kings["K"][0], min(kings["K"][1], kings["k"][1]), max(kings["K"][1], kings["k"][1])
    return all(board[r][file] is None for r in range(lo + 1, hi))


def _structural_problems(board: Board) -> list[str]:
    problems: list[str] = []
    counts = Counter(sq for row in board for sq in row if sq)
    for side, name in (("w", "Red"), ("b", "Black")):
        for kind, limit in MAX_COUNT.items():
            p = kind if side == "w" else kind.lower()
            if counts[p] > limit:
                problems.append(f"{name} has {counts[p]} {kind} (max {limit})")
        k = "K" if side == "w" else "k"
        if counts[k] != 1:
            problems.append(f"{name} must have exactly one king, has {counts[k]}")
    for r, row in enumerate(board):
        for f, sq in enumerate(row):
            if sq is None:
                continue
            side, kind, at = _side_of(sq), sq.upper(), (f, r)
            where = f"{sq} at {FILES[f]}{r}"
            if kind == "K" and at not in _own(_RED_PALACE, side):
                problems.append(f"{where}: king outside palace")
            elif kind == "A" and at not in _own(_RED_ADVISOR, side):
                problems.append(f"{where}: advisor not on a palace point")
            elif kind == "B" and at not in _own(_RED_ELEPHANT, side):
                problems.append(f"{where}: elephant not on a legal elephant point")
            elif kind == "P":
                rel = r if side == "w" else 9 - r  # rank counted from own back rank
                if rel < 3:
                    problems.append(f"{where}: pawn behind its starting rank")
                elif rel < 5 and f % 2:
                    problems.append(f"{where}: pawn on an illegal square before crossing the river")
    if _kings_facing(board):
        problems.append("kings face each other on an open file")
    return problems


def validate_position(board: Sequence[Sequence[str | None]], side: Side | None = None) -> list[str]:
    """Problems that make the position impossible. Empty list = plausible.

    With `side` (side to move) also checks that the side NOT to move is not in check.
    """
    try:
        norm = normalize_board(board)
    except FenError as e:
        return [str(e)]
    problems = _structural_problems(norm)
    if problems:
        return problems  # pyffish is only consulted on structurally sound boards
    fen = board_to_fen(norm, side or "w")
    if sf.validate_fen(fen, VARIANT) != sf.FEN_OK:
        return ["position rejected by rules engine"]
    if side is not None:
        other = board_to_fen(norm, "b" if side == "w" else "w")
        if sf.gives_check(VARIANT, other, []):
            problems.append("side not to move is in check")
    return problems


def _checked_fen(fen: str) -> str:
    """Parse, normalize and make sure pyffish can safely play from this FEN."""
    pos = parse_fen(fen)
    counts = Counter(sq for row in pos.board for sq in row if sq in ("K", "k"))
    if counts["K"] != 1 or counts["k"] != 1:
        raise FenError("each side must have exactly one king")
    out = to_fen(pos)
    if sf.validate_fen(out, VARIANT) != sf.FEN_OK:
        raise FenError(f"invalid position: {fen!r}")
    # pyffish returns garbage move lists when the side to move could capture the enemy king.
    if _kings_facing(pos.board):
        raise FenError("kings face each other on an open file")
    flipped = to_fen(Position(pos.board, "b" if pos.side == "w" else "w"))
    if sf.gives_check(VARIANT, flipped, []):
        raise FenError("side not to move is in check")
    return out


# ---------------------------------------------------------------- moves


def legal_moves(fen: str) -> list[str]:
    return [from_engine_move(m) for m in sf.legal_moves(VARIANT, _checked_fen(fen), [])]


def is_legal(fen: str, uci: str) -> bool:
    return _UCI_RE.match(uci) is not None and uci in legal_moves(fen)


def apply_move(fen: str, uci: str) -> str:
    fen = _checked_fen(fen)
    if not is_legal(fen, uci):
        raise IllegalMoveError(f"illegal move {uci!r} in {fen!r}")
    return sf.get_fen(VARIANT, fen, [to_engine_move(uci)])


def is_in_check(fen: str) -> bool:
    return bool(sf.gives_check(VARIANT, _checked_fen(fen), []))


def game_status(fen: str) -> GameStatus | None:
    """No legal moves: 'checkmate' if in check, else 'stalemate' (a loss for the side to move in Xiangqi)."""
    if legal_moves(fen):
        return None
    return "checkmate" if is_in_check(fen) else "stalemate"


def perft(fen: str, depth: int) -> int:
    """Leaf count at `depth`. Moves round-trip through our UCI coordinates, so this also tests conversion."""
    root = _checked_fen(fen)

    def count(history: list[str], d: int) -> int:
        moves = [from_engine_move(m) for m in sf.legal_moves(VARIANT, root, history)]
        if d == 1:
            return len(moves)
        return sum(count(history + [to_engine_move(m)], d - 1) for m in moves)

    return count([], depth) if depth > 0 else 1


def find_move_between(
    fen_before: str, board_after: Sequence[Sequence[str | None]], side: Side | None = None
) -> list[str]:
    """Legal moves that turn `fen_before` into `board_after` (placement only).

    side=None tries both sides (side to move unknown, e.g. from vision); otherwise only that side.
    """
    target = normalize_board(board_after)
    before = parse_fen(fen_before)
    sides: Iterable[Side] = (side,) if side else ("w", "b")
    found: list[str] = []
    for s in sides:
        fen = to_fen(Position(before.board, s, before.halfmove, before.fullmove))
        try:
            fen = _checked_fen(fen)
        except FenError:
            continue
        for m in sf.legal_moves(VARIANT, fen, []):
            if parse_fen(sf.get_fen(VARIANT, fen, [m])).board == target:
                found.append(from_engine_move(m))
    return found


def validate_line(fen: str, ucis: Sequence[str]) -> int | None:
    """Index of the first illegal move in `ucis` played from `fen`, or None if the whole line is legal."""
    for i, uci in enumerate(ucis):
        if not is_legal(fen, uci):
            return i
        fen = apply_move(fen, uci)
    return None
