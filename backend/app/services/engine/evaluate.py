"""Evaluate one played move: engine analysis before/after, mapped onto the frontend's EngineAnalysis.

Heuristics (deliberately simple, documented so the coach never over-claims):
- Perspective: every eval here is from the MOVER's side (+ = good for the player who just moved).
- Mate: a mate score is mapped to +-(MATE_CP - n) and flagged in eval_*_mate. cp_loss never subtracts
  two raw mate scores: if both sides of the move are mates for the same side, cp_loss = 0 (still winning /
  already lost); otherwise both evals are clamped to +-MATE_CLAMP_CP first (missing a forced mate or
  walking into one costs at most MATE_CLAMP_CP).
- threats.check: the opponent's best reply gives check.
- threats.capture: any of the opponent's top-3 replies captures one of the mover's pieces.
- threats.counterattack: the opponent has a forced mate, or the move lost >= COUNTERATTACK_CP.
- material_at_risk: the opponent's best reply captures a mover piece and its PV does not show the mover
  recapturing a piece of at least equal value on the next ply.
- stable: best move unchanged and best score within STABLE_CP over the last 3 completed depths.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.services.engine.explain import MoveExplanation, explain, null_move_fen
from app.services.engine.manager import DEFAULT_DEPTH, AnalysisResult, EngineManager, EngineUnavailable
from app.services.engine.uci import MATE_CP
from app.services.rules import xiangqi as rules

log = logging.getLogger(__name__)

MATE_CLAMP_CP = 2000
COUNTERATTACK_CP = 150
STABLE_CP = 30
REPLIES = 3
PIECE_VALUE = {"P": 100, "A": 200, "B": 200, "N": 400, "C": 450, "R": 900, "K": 100_000}


class RiskFlags(BaseModel):
    check: bool
    capture: bool
    counterattack: bool


class MoveEvaluation(BaseModel):
    """1:1 with desktop/src/types/moveReview.ts EngineAnalysis, plus quality/debug fields."""

    source: str = "pikafish"
    eval_before_cp: int
    eval_after_cp: int
    best_move: str
    opponent_best_replies: list[str]
    principal_variation: list[str]
    threats: RiskFlags
    material_at_risk: bool
    # extras
    move: str
    fen_after: str
    eval_before_mate: int | None  # mover perspective, moves to mate (>0 = mover mates); 0 = mate delivered
    eval_after_mate: int | None
    cp_loss: int
    depth: int  # min depth reached by the two searches
    depth_requested: int
    stable: bool
    notes: list[str]
    before: AnalysisResult
    after: AnalysisResult
    explanation: MoveExplanation | None = None  # plain-language facts; None if they could not be derived


def _piece_at(fen: str, sq: str) -> str | None:
    return rules.parse_fen(fen).board[int(sq[1])][rules.FILES.index(sq[0])]


def _captured(fen: str, uci: str) -> str | None:
    return _piece_at(fen, uci[2:4])


def is_stable(result: AnalysisResult) -> bool:
    last = result.history[-3:]
    if result.game_over:
        return True
    if len(last) < 3 or len({h.best_move for h in last}) != 1:
        return False
    if any(h.mate is not None for h in last):
        return len({h.mate is not None and h.mate > 0 for h in last}) == 1
    scores = [h.score_cp for h in last]
    return max(scores) - min(scores) <= STABLE_CP


def cp_loss(before_cp: int, before_mate: int | None, after_cp: int, after_mate: int | None) -> int:
    if before_mate is not None and after_mate is not None and (before_cp > 0) == (after_cp > 0):
        return 0
    clamp = lambda v: max(-MATE_CLAMP_CP, min(MATE_CLAMP_CP, v))  # noqa: E731
    return max(0, clamp(before_cp) - clamp(after_cp))


def _material_at_risk(fen_after: str, pv: list[str]) -> bool:
    if not pv:
        return False
    taken = _captured(fen_after, pv[0])
    if taken is None:
        return False
    if len(pv) < 2:
        return True
    retaken = _captured(rules.apply_move(fen_after, pv[0]), pv[1])
    return retaken is None or PIECE_VALUE[retaken.upper()] < PIECE_VALUE[taken.upper()]


async def evaluate_move(manager: EngineManager, fen_before: str, move: str, depth: int | None = None) -> MoveEvaluation:
    """Raises rules.FenError / rules.IllegalMoveError on bad input, EngineUnavailable without engine."""
    fen_after = rules.apply_move(fen_before, move)  # validates FEN + legality
    before = await manager.analyze(fen_before, depth=depth, multipv=1)
    after = await manager.analyze(fen_after, depth=depth, multipv=REPLIES)
    requested = before.depth_requested or DEFAULT_DEPTH
    if not before.lines or not (after.lines or after.game_over):
        raise EngineUnavailable("Pikafish không trả về biến hợp lệ cho thế cờ này.")

    b = before.lines[0]
    before_cp, before_mate = b.score_cp, b.mate
    if after.game_over:  # opponent has no move: checkmate, and stalemate also loses in Xiangqi
        after_cp, after_mate = MATE_CP, 0
    else:
        a = after.lines[0]
        after_cp, after_mate = -a.score_cp, (-a.mate if a.mate is not None else None)
    loss = cp_loss(before_cp, before_mate, after_cp, after_mate)

    replies = [ln.pv[0] for ln in after.lines]
    pv = after.lines[0].pv if after.lines else []
    gives_check = bool(pv) and rules.is_in_check(rules.apply_move(fen_after, pv[0]))
    threats = RiskFlags(
        check=gives_check,
        capture=any(_captured(fen_after, r) is not None for r in replies),
        counterattack=(after_mate is not None and after_mate < 0) or loss >= COUNTERATTACK_CP,
    )

    reached = min(before.depth or requested, after.depth or requested)
    stable = is_stable(before) and is_stable(after)
    notes: list[str] = []
    if reached < requested:
        notes.append(f"Phân tích chưa đủ sâu (đạt độ sâu {reached}/{requested}).")
    if not stable:
        notes.append("Đánh giá của engine chưa ổn định giữa các độ sâu, cần thận trọng khi kết luận.")
    if before.timed_out or after.timed_out:
        notes.append("Engine bị dừng do hết thời gian, kết quả có thể chưa chính xác.")
    if before.warnings or after.warnings:
        notes.append("Đã loại bỏ nước đi không hợp lệ trong biến của engine.")

    # The opponent's intent: their best move if it were their turn in the position before the player's move.
    intent = None
    null_fen = null_move_fen(fen_before)
    if null_fen is not None:
        threat = await manager.analyze(null_fen, depth=depth, multipv=1)
        intent = threat.best_move or (threat.lines[0].pv[0] if threat.lines and threat.lines[0].pv else None)
    best_line = b.pv or ([before.best_move] if before.best_move else [])
    try:
        explanation = explain(fen_before, move, best_line, pv[0] if pv else None, intent)
    except (rules.FenError, rules.IllegalMoveError):
        log.warning("move explanation failed", extra={"move": move})
        explanation = None

    return MoveEvaluation(
        explanation=explanation,
        eval_before_cp=before_cp,
        eval_after_cp=after_cp,
        best_move=before.best_move or b.pv[0],
        opponent_best_replies=replies,
        principal_variation=pv,
        threats=threats,
        material_at_risk=_material_at_risk(fen_after, pv),
        move=move,
        fen_after=fen_after,
        eval_before_mate=before_mate,
        eval_after_mate=after_mate,
        cp_loss=loss,
        depth=reached,
        depth_requested=requested,
        stable=stable,
        notes=notes,
        before=before,
        after=after,
    )
