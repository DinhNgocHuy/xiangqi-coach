"""Training Center: exercises built ONLY from the player's real positions + Pikafish analysis.

Source = a thinking_mistakes row (session, move) joined with the recorded move (fen_before, uci).
No engine -> no exercise (a reason is returned instead); solutions are never invented.

Exercise types (component -> type, position, answer):
- threatAwareness      -> threat_detection      fen_after,  opponent move: engine replies within ACCEPT_CP of the
                          best that give check or capture; skipped when the engine sees no such threat.
- responsePrediction   -> response_prediction   fen_after,  opponent move: replies within ACCEPT_CP of the best.
- variationCalculation -> variation_calculation fen_before, player move: moves within ACCEPT_CP of the best
                          (graded on the first move; the PV is shown after the attempt).
- positionEvaluation   -> position_evaluation   fen_after,  eval class for the player (better/equal/worse, ±EVAL_CP).
- pieceSafety          -> defensive_awareness   fen_before, player move: moves within ACCEPT_CP of the best that
                          do not leave material at risk; skipped when none qualifies.

"Within ACCEPT_CP" compares centipawns only. When the best line is a mate, a move is accepted only if it also
mates for the same side with a distance within 1 of the best (mate in N -> mate in <= N+1; mated in N -> mated in
>= N-1); mapped mate scores (±(MATE_CP - n)) are never subtracted. Timed-out analyses and analyses with warnings
(illegal engine output) produce no exercise.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.core.db import db_lock
from app.services.engine.evaluate import _material_at_risk
from app.services.engine.manager import AnalysisResult, EngineManager, EngineUnavailable
from app.services.journal import LABELS
from app.services.rules import xiangqi as rules

ACCEPT_CP = 30
EVAL_CP = 50  # same class thresholds as the frontend (moveReview.ts engineClass)
TRAINING_DEPTH = 12
MULTIPV = 5
EVAL_CLASSES = ("better", "equal", "worse")
EVAL_LABEL = {"better": "tốt hơn", "equal": "cân bằng", "worse": "kém hơn"}
SIDE_LABEL = {"w": "Đỏ", "b": "Đen"}

TYPES = {
    "threatAwareness": "threat_detection",
    "responsePrediction": "response_prediction",
    "variationCalculation": "variation_calculation",
    "positionEvaluation": "position_evaluation",
    "pieceSafety": "defensive_awareness",
}
_AFTER = {"threat_detection", "response_prediction", "position_evaluation"}


class ExerciseNotFound(LookupError):
    pass


class InvalidAnswer(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _accepted(result: AnalysisResult) -> list[str]:
    if not result.lines:
        return []
    best = result.lines[0]
    if best.mate is not None:
        return [
            ln.pv[0] for ln in result.lines
            if ln.mate is not None and (ln.mate > 0) == (best.mate > 0) and abs(ln.mate - best.mate) <= 1
        ]  # fmt: skip
    return [ln.pv[0] for ln in result.lines if ln.mate is None and ln.score_cp >= best.score_cp - ACCEPT_CP]


def _eval_text(solution: dict[str, Any]) -> str:
    """The player's evaluation in words: centipawns, or mate distance (never a mapped mate score as cp)."""
    mate = solution.get("player_mate")
    if mate is None:
        return f"{solution['player_eval_cp']:+d} cp"
    return f"bạn chiếu hết sau {mate} nước" if mate > 0 else f"bạn bị chiếu hết sau {-mate} nước"


def _is_threat(fen: str, mv: str) -> bool:
    return rules.parse_fen(fen).board[int(mv[3])][rules.FILES.index(mv[2])] is not None or rules.is_in_check(
        rules.apply_move(fen, mv)
    )


def _prompt(kind: str, played: str, side: str) -> str:
    you = SIDE_LABEL[side]
    return {
        "threat_detection": f"Bạn (bên {you}) vừa đi {played}. Đối thủ có nước đe dọa nào (chiếu hoặc bắt quân)? "
        "Nhập nước nguy hiểm nhất của đối thủ.",
        "response_prediction": f"Bạn (bên {you}) vừa đi {played}. Nước đáp trả mạnh nhất của đối thủ là gì?",
        "variation_calculation": f"Thế cờ từ ván của bạn, bên {you} đi. Hãy tính biến và chọn nước đi tốt nhất.",
        "position_evaluation": f"Bạn (bên {you}) vừa đi {played}. Thế cờ của bạn bây giờ tốt hơn, cân bằng hay kém hơn?",
        "defensive_awareness": f"Thế cờ từ ván của bạn, bên {you} đi. Hãy tìm nước đi giữ an toàn cho quân của bạn.",
    }[kind]


async def build_exercise(manager: EngineManager, component: str, fen_before: str, played: str) -> dict[str, Any]:
    """Exercise fields + solution. Raises EngineUnavailable; ValueError(reason) when no honest exercise exists."""
    kind = TYPES[component]
    fen_after = rules.apply_move(fen_before, played)  # validates FEN + recorded move
    fen = fen_after if kind in _AFTER else fen_before
    if rules.game_status(fen):
        raise ValueError("Ván cờ đã kết thúc ở thế này, không có nước để luyện.")
    result = await manager.analyze(fen, depth=TRAINING_DEPTH, multipv=MULTIPV)
    if not result.lines:
        raise EngineUnavailable("Pikafish không trả về biến hợp lệ cho thế cờ này.")
    if result.timed_out or result.warnings:
        raise ValueError("Phân tích của engine chưa hoàn chỉnh (hết giờ hoặc có cảnh báo), không tạo bài tập.")
    best = result.lines[0]
    solution: dict[str, Any] = {
        "best_move": best.pv[0],
        "eval_cp": best.score_cp,  # side to move in `fen`
        "mate": best.mate,
        "principal_variation": best.pv,
        "depth_requested": result.depth_requested,
        "accept_cp": ACCEPT_CP,
    }
    if kind == "position_evaluation":
        cp = -best.score_cp  # the player is NOT to move in fen_after
        solution["eval_class"] = "better" if cp > EVAL_CP else "worse" if cp < -EVAL_CP else "equal"
        solution["player_eval_cp"] = cp
        solution["player_mate"] = -best.mate if best.mate is not None else None
        solution["accepted_moves"] = []
    else:
        accepted = _accepted(result)
        if kind == "threat_detection":
            accepted = [m for m in accepted if _is_threat(fen, m)]
            if not accepted:
                raise ValueError("Engine không thấy nước đe dọa thật (chiếu/bắt quân) ở thế này.")
        elif kind == "defensive_awareness":
            pvs = {ln.pv[0]: ln.pv for ln in result.lines}
            accepted = [m for m in accepted if not _material_at_risk(rules.apply_move(fen, m), pvs[m][1:])]
            if not accepted:
                raise ValueError("Engine không tìm được nước giữ an toàn quân trong các nước tốt nhất.")
        solution["accepted_moves"] = accepted
    for mv in [*solution["accepted_moves"], solution["best_move"]]:
        if not rules.is_legal(fen, mv):  # never store an engine move the rules reject
            raise ValueError(f"Nước của engine {mv} không hợp lệ.")
    side = rules.parse_fen(fen).side
    # The player's side: in fen_after it is the opponent's turn.
    player_side = rules.parse_fen(fen_before).side
    return {
        "type": kind,
        "fen": fen,
        "side_to_move": side,
        "answer_kind": "eval" if kind == "position_evaluation" else "move",
        "prompt": _prompt(kind, played, player_side),
        "solution": solution,
        "engine_depth": result.depth,
    }


def _candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Mistakes, most frequent component first, then most recent."""
    return conn.execute(
        "SELECT t.session_id, t.move_number, t.component, m.fen_before, m.uci FROM thinking_mistakes t "
        "JOIN moves m ON m.session_id = t.session_id AND m.move_number = t.move_number "
        "JOIN (SELECT component, COUNT(*) AS n, MAX(created_at) AS last FROM thinking_mistakes GROUP BY component) c "
        "ON c.component = t.component "
        "ORDER BY c.n DESC, c.last DESC, t.created_at DESC, t.id DESC"
    ).fetchall()


def _exists(conn: sqlite3.Connection, session_id: str, move_number: int, kind: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM exercises WHERE session_id = ? AND move_number = ? AND type = ?", (session_id, move_number, kind)
    ).fetchone()
    return row is not None


def _store(conn: sqlite3.Connection, c: sqlite3.Row, ex: dict[str, Any]) -> dict[str, Any] | None:
    # The move may have been undone while the engine was thinking: store only if it is still the same move.
    if conn.execute(
        "SELECT 1 FROM moves WHERE session_id = ? AND move_number = ? AND uci = ?",
        (c["session_id"], c["move_number"], c["uci"]),
    ).fetchone() is None:
        return None
    cur = conn.execute(
        "INSERT OR IGNORE INTO exercises (session_id, move_number, component, type, fen, side_to_move, played_move, "
        "answer_kind, prompt, solution_json, engine_depth, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (c["session_id"], c["move_number"], c["component"], ex["type"], ex["fen"], ex["side_to_move"], c["uci"],
         ex["answer_kind"], ex["prompt"], json.dumps(ex["solution"]), ex["engine_depth"], _now()),
    )  # fmt: skip
    return get_exercise(conn, cur.lastrowid) if cur.rowcount else None  # type: ignore[arg-type]


async def _db(fn: Any, *args: Any) -> Any:
    """Run a DB step in a worker thread under db_lock: never hold the lock on the event loop."""

    def run() -> Any:
        with db_lock:
            return fn(*args)

    return await asyncio.to_thread(run)


async def generate(conn: sqlite3.Connection, manager: EngineManager, limit: int = 5) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    candidates = await _db(_candidates, conn)
    if not candidates:
        return {"created": [], "skipped": [], "reason": "Chưa có lỗi tư duy nào để tạo bài tập."}
    for c in candidates:
        if len(created) >= limit:
            break
        kind = TYPES.get(c["component"])
        if kind is None:
            continue
        src = {"session_id": c["session_id"], "move_number": c["move_number"], "component": c["component"]}
        if await _db(_exists, conn, c["session_id"], c["move_number"], kind):
            continue  # duplicate
        try:
            ex = await build_exercise(manager, c["component"], c["fen_before"], c["uci"])
        except EngineUnavailable as e:
            # Engine missing/dead applies to every candidate: stop instead of failing N times.
            return {"created": created, "skipped": skipped, "reason": str(e)}
        except (ValueError, rules.FenError, rules.IllegalMoveError) as e:
            skipped.append({**src, "reason": str(e)})
            continue
        if stored := await _db(_store, conn, c, ex):
            created.append(stored)
    return {"created": created, "skipped": skipped, "reason": None if created else "Không tạo được bài tập mới."}


def _public(row: sqlite3.Row, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    ex = {k: row[k] for k in ("id", "session_id", "move_number", "component", "type", "fen", "side_to_move",
                              "answer_kind", "prompt", "engine_depth", "created_at")}  # fmt: skip
    ex["component_label"] = LABELS.get(row["component"], row["component"])
    ex["status"] = "done" if attempts else "pending"
    ex["attempts"] = attempts
    # The solution (and the played move, which is part of it for fen_before types) is revealed only after an attempt.
    ex["played_move"] = row["played_move"] if attempts or row["type"] in _AFTER else None
    ex["solution"] = json.loads(row["solution_json"]) if attempts else None
    return ex


def get_exercise(conn: sqlite3.Connection, exercise_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    if row is None:
        raise ExerciseNotFound(exercise_id)
    attempts = conn.execute(
        "SELECT answer, correct, created_at FROM exercise_attempts WHERE exercise_id = ? ORDER BY id", (exercise_id,)
    )
    return _public(row, [{**dict(a), "correct": bool(a["correct"])} for a in attempts])


def list_exercises(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    ids = [r[0] for r in conn.execute("SELECT id FROM exercises ORDER BY created_at DESC, id DESC")]
    items = [get_exercise(conn, i) for i in ids]
    return [e for e in items if status is None or e["status"] == status]


def attempt(conn: sqlite3.Connection, exercise_id: int, answer: str) -> dict[str, Any]:
    with db_lock:
        return _attempt(conn, exercise_id, answer)


def _attempt(conn: sqlite3.Connection, exercise_id: int, answer: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    if row is None:
        raise ExerciseNotFound(exercise_id)
    solution = json.loads(row["solution_json"])
    answer = answer.strip().lower()
    if row["answer_kind"] == "eval":
        if answer not in EVAL_CLASSES:
            raise InvalidAnswer(f"Câu trả lời phải là một trong: {', '.join(EVAL_CLASSES)}.")
        correct = answer == solution["eval_class"]
        explanation = (
            f"Engine (độ sâu {row['engine_depth']}) đánh giá thế cờ của bạn {_eval_text(solution)}: "
            f"{EVAL_LABEL[solution['eval_class']]}."
        )
    else:
        if not rules.is_legal(row["fen"], answer):
            raise InvalidAnswer(f"Nước {answer} không hợp lệ ở thế cờ này.")
        correct = answer in solution["accepted_moves"]
        rule = f"cách nước tốt nhất ≤ {solution['accept_cp']} cp"
        if (mate := solution.get("mate")) is not None:
            rule = f"chiếu hết sau ≤ {mate + 1} nước" if mate > 0 else f"cầm cự ≥ {-mate - 1} nước trước khi bị chiếu"
        explanation = (
            f"Nước được chấp nhận ({rule}, độ sâu {row['engine_depth']}): "
            f"{', '.join(solution['accepted_moves'])}. Biến chính của engine: {' '.join(solution['principal_variation'])}."
        )
    conn.execute(
        "INSERT INTO exercise_attempts (exercise_id, answer, correct, created_at) VALUES (?, ?, ?, ?)",
        (exercise_id, answer, int(correct), _now()),
    )
    return {
        "correct": correct,
        "explanation": ("Chính xác. " if correct else "Chưa đúng. ") + explanation,
        "exercise": get_exercise(conn, exercise_id),
    }
