"""Thinking Journal + Dashboard stats over stored MoveReviews (SQLite). Never fabricates numbers.

Rules (documented in docs/ARCHITECTURE.md §10):
- A thinking mistake = an ANSWERED component (not null) with score < 1. Unanswered parts are not mistakes.
- recurring: the component was a mistake in >= RECURRING_MIN of the last RECURRING_WINDOW reviewed moves.
- trend: average component score per ISO week (answered only). direction compares the last two weeks with
  data: >= +TREND_DELTA improving, <= -TREND_DELTA worsening, else flat; < 2 weeks -> insufficient_data.
- skills_to_improve: lowest average components with >= MIN_SAMPLES answers.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.db import db_lock, transaction
from app.schemas.review import COMPONENTS, MoveReviewIn, StoredReview
from app.services import tracker as tr

RECURRING_WINDOW = 10
RECURRING_MIN = 3
TREND_DELTA = 0.1
MIN_SAMPLES = 5
NO_DATA = "Chưa có dữ liệu"
NOT_ENOUGH = "Chưa đủ dữ liệu"

LABELS = {
    "threatAwareness": "Nhận diện đe dọa",
    "responsePrediction": "Dự đoán nước đáp trả",
    "variationCalculation": "Tính biến",
    "positionEvaluation": "Đánh giá thế cờ",
    "pieceSafety": "An toàn quân cờ",
}
# Substrings of the frontend's missed_threats texts (moveReview.ts) that belong to each component.
_MISSED_KEYS = {
    "threatAwareness": ("nguy cơ",),
    "responsePrediction": ("Bạn dự đoán",),
    "variationCalculation": ("đã tính",),
    "positionEvaluation": ("đánh giá thế cờ",),
    "pieceSafety": ("có thể bị mất",),
}


class MoveNotFound(LookupError):
    pass


class ReviewMismatch(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _describe(component: str, score: float, missed: list[str]) -> str:
    for text in missed:
        if any(k in text for k in _MISSED_KEYS[component]):
            return text[:300]
    return f"{LABELS[component]}: chưa chính xác (điểm {score:g}/1)."


def save_review(conn: sqlite3.Connection, session_id: str, review: MoveReviewIn) -> StoredReview:
    """Upsert by (session_id, move_number) and re-derive that move's thinking_mistakes."""
    if review.session_id != session_id:
        raise ReviewMismatch("session_id trong nhận xét không khớp với buổi tập.")
    with db_lock:
        if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise tr.SessionNotFound(session_id)
        move = conn.execute(
            "SELECT uci, fen_before FROM moves WHERE session_id = ? AND move_number = ?",
            (session_id, review.move_number),
        ).fetchone()
        if move is None:
            raise MoveNotFound(review.move_number)
        if review.player_move.strip().lower() != move["uci"]:
            raise ReviewMismatch(f"Nước {review.player_move} không khớp nước đã ghi ({move['uci']}).")

        comps = review.thinking_components.model_dump()
        mistakes = [c for c in COMPONENTS if comps[c] is not None and comps[c] < 1]
        with transaction(conn):
            conn.execute(
                "INSERT INTO move_reviews (session_id, move_number, review_json, move_quality_score, "
                "thinking_quality_score, created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (session_id, move_number) DO UPDATE SET review_json = excluded.review_json, "
                "move_quality_score = excluded.move_quality_score, "
                "thinking_quality_score = excluded.thinking_quality_score",
                (session_id, review.move_number, review.model_dump_json(), review.move_quality_score,
                 review.thinking_quality_score, _now()),
            )  # fmt: skip
            created = conn.execute(
                "SELECT created_at FROM move_reviews WHERE session_id = ? AND move_number = ?",
                (session_id, review.move_number),
            ).fetchone()[0]
            conn.execute(
                "DELETE FROM thinking_mistakes WHERE session_id = ? AND move_number = ?",
                (session_id, review.move_number),
            )
            conn.executemany(
                "INSERT INTO thinking_mistakes (session_id, move_number, component, description, fen, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (session_id, review.move_number, c, _describe(c, comps[c], review.missed_threats),
                     move["fen_before"], created)
                    for c in mistakes
                ],
            )  # fmt: skip
    return list_reviews(conn, session_id, review.move_number)[0]


def list_reviews(conn: sqlite3.Connection, session_id: str, move_number: int | None = None) -> list[StoredReview]:
    if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
        raise tr.SessionNotFound(session_id)
    sql = "SELECT * FROM move_reviews WHERE session_id = ?"
    args: tuple[Any, ...] = (session_id,)
    if move_number is not None:
        sql += " AND move_number = ?"
        args += (move_number,)
    out = []
    for r in conn.execute(sql + " ORDER BY move_number", args).fetchall():
        mistakes = conn.execute(
            "SELECT component FROM thinking_mistakes WHERE session_id = ? AND move_number = ? ORDER BY id",
            (session_id, r["move_number"]),
        )
        out.append(
            StoredReview(
                session_id=session_id, move_number=r["move_number"], move_quality_score=r["move_quality_score"],
                thinking_quality_score=r["thinking_quality_score"], created_at=r["created_at"],
                review=json.loads(r["review_json"]), mistakes=[m[0] for m in mistakes],
            )  # fmt: skip
        )
    return out


# ---------------------------------------------------------------- journal


def list_mistakes(
    conn: sqlite3.Connection,
    component: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    where, args = [], []
    if component:
        where.append("component = ?")
        args.append(component)
    if date_from:
        where.append("created_at >= ?")
        args.append(date_from.isoformat())
    if date_to:  # inclusive day
        where.append("created_at < ?")
        args.append((date_to + timedelta(days=1)).isoformat())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM thinking_mistakes{clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, session_id, move_number, component, description, fen, created_at FROM thinking_mistakes{clause} "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    )
    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


def _reviews(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """All reviews, oldest first, with parsed thinking components."""
    rows = conn.execute(
        "SELECT review_json, move_quality_score, thinking_quality_score, created_at FROM move_reviews "
        "ORDER BY created_at, id"
    )
    return [
        {
            "created_at": r["created_at"],
            "move_quality": r["move_quality_score"],
            "thinking": r["thinking_quality_score"],
            "components": json.loads(r["review_json"]).get("thinking_components", {}),
        }
        for r in rows
    ]


def _week(ts: str) -> str:
    y, w, _ = datetime.fromisoformat(ts).isocalendar()
    return f"{y}-W{w:02d}"


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _direction(trend: list[dict[str, Any]]) -> str:
    if len(trend) < 2:
        return "insufficient_data"
    diff = trend[-1]["avg_score"] - trend[-2]["avg_score"]
    return "improving" if diff >= TREND_DELTA else "worsening" if diff <= -TREND_DELTA else "flat"


def patterns(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = {r[0]: r[1:] for r in conn.execute(
        "SELECT component, COUNT(*), MAX(created_at) FROM thinking_mistakes GROUP BY component"
    )}  # fmt: skip
    total = sum(c for c, _ in counts.values())
    reviews = _reviews(conn)
    recent = reviews[-RECURRING_WINDOW:]
    out = []
    for comp in COMPONENTS:
        count, last_seen = counts.get(comp, (0, None))
        weekly: dict[str, list[float]] = {}
        for r in reviews:
            v = r["components"].get(comp)
            if v is not None:
                weekly.setdefault(_week(r["created_at"]), []).append(v)
        trend = [{"week": w, "avg_score": _avg(v), "samples": len(v)} for w, v in sorted(weekly.items())]
        recent_misses = sum(1 for r in recent if (v := r["components"].get(comp)) is not None and v < 1)
        out.append({
            "component": comp,
            "label": LABELS[comp],
            "count": count,
            "share": round(count / total, 3) if total else None,
            "last_seen": last_seen,
            "recurring": recent_misses >= RECURRING_MIN,
            "recent_mistakes": recent_misses,
            "trend": trend,
            "direction": _direction(trend),
        })  # fmt: skip
    return {
        "total_mistakes": total,
        "reviewed_moves": len(reviews),
        "rule": f"Lặp lại = sai ≥ {RECURRING_MIN} lần trong {RECURRING_WINDOW} nước được đánh giá gần nhất.",
        "message": None if reviews else NO_DATA,
        "components": out,
    }


# ---------------------------------------------------------------- dashboard


def _series(reviews: list[dict[str, Any]], key) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in reviews:
        groups.setdefault(key(r["created_at"]), []).append(r)
    return [
        {
            "period": p,
            "reviews": len(rs),
            "avg_thinking": _avg([r["thinking"] for r in rs if r["thinking"] is not None]),
            "avg_move_quality": _avg([r["move_quality"] for r in rs if r["move_quality"] is not None]),
        }
        for p, rs in sorted(groups.items())
    ]


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    reviews = _reviews(conn)
    sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    thinking = [r["thinking"] for r in reviews if r["thinking"] is not None]
    quality = [r["move_quality"] for r in reviews if r["move_quality"] is not None]
    mistakes = conn.execute(
        "SELECT component, COUNT(*) AS n FROM thinking_mistakes GROUP BY component ORDER BY n DESC, component"
    ).fetchall()

    per_comp = {c: [v for r in reviews if (v := r["components"].get(c)) is not None] for c in COMPONENTS}
    skills = sorted(
        ({"component": c, "label": LABELS[c], "avg_score": _avg(v), "samples": len(v)}
         for c, v in per_comp.items() if len(v) >= MIN_SAMPLES),
        key=lambda s: s["avg_score"],
    )  # fmt: skip
    return {
        "message": None if reviews or sessions else NO_DATA,
        "total_sessions": sessions,
        "total_reviewed_moves": len(reviews),
        "avg_thinking_score": _avg(thinking),
        "avg_move_quality": _avg(quality),
        "thinking_samples": len(thinking),
        "move_quality_samples": len(quality),
        "null_thinking_reviews": len(reviews) - len(thinking),
        "null_thinking_label": NOT_ENOUGH.lower(),
        "common_mistakes": [{"component": m[0], "label": LABELS.get(m[0], m[0]), "count": m[1]} for m in mistakes[:3]],
        "weekly": _series(reviews, _week),
        "monthly": _series(reviews, lambda ts: ts[:7]),
        "skills_to_improve": [s for s in skills if s["avg_score"] < 1][:3],
        "skills_message": None
        if skills
        else f"{NOT_ENOUGH}: cần ít nhất {MIN_SAMPLES} câu trả lời cho mỗi kỹ năng.",
    }
