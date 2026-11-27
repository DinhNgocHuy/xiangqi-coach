"""Plain-language facts about moves, from the rules and Pikafish only (no LLM, nothing invented).

- notation(): Vietnamese notation ("Pháo 2 bình 5"); files are counted from each side's own right.
- reasons(): what a move does right away: capture, check, new attacks on pieces that are unprotected or
  worth more than the attacker (checked by "can the opponent recapture on that square").
- The opponent's intent = Pikafish's best move for the opponent if it were their turn before the player's
  move (a "null move"). Not computed when the player is in check (the check is the intent).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.services.rules import xiangqi as rules

NAMES = {"K": "Tướng", "A": "Sĩ", "B": "Tượng", "N": "Mã", "R": "Xe", "C": "Pháo", "P": "Tốt"}
VALUE = {"P": 100, "A": 200, "B": 200, "N": 400, "C": 450, "R": 900, "K": 100_000}
LINE_PLIES = 6


class MoveExplanation(BaseModel):
    player_move: str
    player_reasons: list[str]
    best_move: str
    best_reasons: list[str]
    best_line: list[str]  # notation, starting with the best move
    opponent_reply: str | None
    opponent_reply_reasons: list[str]
    opponent_intent: str | None  # what the opponent wanted to play before the player's move
    opponent_intent_reasons: list[str]
    intent_handled: bool | None  # None = no concrete threat to handle


def _sq(s: str) -> tuple[int, int]:
    return rules.FILES.index(s[0]), int(s[1:])


def _piece(fen: str, s: str) -> str | None:
    f, r = _sq(s)
    return rules.parse_fen(fen).board[r][f]


def _flip(fen: str) -> str:
    """Same placement, other side to move. Raises FenError when that side could take the king."""
    pos = rules.parse_fen(fen)
    out = rules.to_fen(rules.Position(pos.board, "b" if pos.side == "w" else "w"))
    rules.legal_moves(out)  # validates
    return out


def notation(fen: str, uci: str) -> str:
    board = rules.parse_fen(fen).board
    (f1, r1), (f2, r2) = _sq(uci[:2]), _sq(uci[2:])
    p = board[r1][f1]
    if p is None:
        return uci
    red, kind = p.isupper(), p.upper()
    col = (lambda f: 9 - f) if red else (lambda f: f + 1)
    # Two identical pieces on one file: "trước/sau" (front/back) replaces the file number.
    same = [r for r in range(rules.RANKS) if board[r][f1] == p]
    where = str(col(f1))
    if len(same) == 2 and kind != "P":
        front = max(same) if red else min(same)
        where = "trước" if r1 == front else "sau"
    if r1 == r2:
        action, n = "bình", col(f2)
    else:
        action = "tiến" if (r2 > r1) == red else "thoái"
        n = abs(r2 - r1) if kind in "KRCP" else col(f2)
    return f"{NAMES[kind]} {where} {action} {n}"


def _targets(fen: str) -> dict[str, str]:
    """Square -> enemy piece the side to move can capture."""
    out = {}
    for m in rules.legal_moves(fen):
        t = _piece(fen, m[2:])
        if t is not None:
            out[m[2:]] = t
    return out


def _protected(fen: str, capture: str) -> bool:
    """After the side to move plays `capture`, can the other side take back on that square?"""
    after = rules.apply_move(fen, capture)
    return any(m[2:] == capture[2:] for m in rules.legal_moves(after))


def reasons(fen: str, uci: str) -> list[str]:
    """What `uci` (legal in `fen`) does right away, from the mover's side."""
    out: list[str] = []
    taken = _piece(fen, uci[2:])
    if taken is not None:
        out.append(f"ăn {NAMES[taken.upper()]}")
    after = rules.apply_move(fen, uci)
    if rules.is_in_check(after):
        out.append("chiếu Tướng")
        return out  # the threat is the check itself; a null move is not legal here
    try:
        again = _flip(after)  # the mover to move again: what does it attack now?
    except rules.FenError:
        return out
    before = _targets(fen)
    for sq, t in _targets(again).items():
        if sq in before or t.upper() == "K":
            continue
        attackers = [m for m in rules.legal_moves(again) if m[2:] == sq]
        cheapest = min(attackers, key=lambda m: VALUE[(_piece(again, m[:2]) or "P").upper()])
        a = (_piece(again, cheapest[:2]) or "P").upper()
        if not _protected(again, cheapest):
            out.append(f"đe dọa ăn {NAMES[t.upper()]} (không được bảo vệ)")
        elif VALUE[t.upper()] > VALUE[a]:
            out.append(f"đe dọa dùng {NAMES[a]} đổi lấy {NAMES[t.upper()]}")
    return out


def line(fen: str, moves: list[str], plies: int = LINE_PLIES) -> list[str]:
    out = []
    for m in moves[:plies]:
        try:
            out.append(notation(fen, m))
            fen = rules.apply_move(fen, m)
        except (rules.FenError, rules.IllegalMoveError):
            break
    return out


def explain(
    fen_before: str, move: str, best_line: list[str], reply: str | None, intent: str | None
) -> MoveExplanation:
    fen_after = rules.apply_move(fen_before, move)
    best = best_line[0] if best_line else move
    handled = None
    intent_reasons: list[str] = []
    if intent:
        flipped = _flip(fen_before)
        intent_reasons = reasons(flipped, intent)
        # A concrete threat (capture/check) is handled when it no longer works the same way after the move.
        if intent_reasons:
            still = rules.is_legal(fen_after, intent) and reasons(fen_after, intent)[:1] == intent_reasons[:1]
            handled = not still
    return MoveExplanation(
        player_move=notation(fen_before, move),
        player_reasons=reasons(fen_before, move),
        best_move=notation(fen_before, best),
        best_reasons=reasons(fen_before, best),
        best_line=line(fen_before, best_line),
        opponent_reply=notation(fen_after, reply) if reply else None,
        opponent_reply_reasons=reasons(fen_after, reply) if reply else [],
        opponent_intent=notation(_flip(fen_before), intent) if intent else None,
        opponent_intent_reasons=intent_reasons,
        intent_handled=handled,
    )


def null_move_fen(fen_before: str) -> str | None:
    """The opponent to move in the same position, or None when the player is in check (null move illegal)."""
    if rules.is_in_check(fen_before):
        return None
    try:
        return _flip(fen_before)
    except rules.FenError:
        return None
