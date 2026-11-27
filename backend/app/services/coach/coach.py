"""Coach one reviewed move with an LLM, then run a deterministic output guard.

The frontend Move Review already scores the move and the thinking (rule-based); the coach only explains those
results. Guard rules (docs/ARCHITECTURE.md §7):
- Every move-like token ([a-i][0-9][a-i][0-9], also written "h2-e2", "h2 e2", "h2→e2", "h2xe2") must be the
  player's move, one of the player's own inputs (predicted reply, variations) or, only when reveal_engine is set,
  an engine move. Any sentence with another token is dropped (`guard.removed`). Sentences in traditional notation
  ("Pháo 2 bình 5", "C2=5", "H8+7", "炮二平五") cannot be checked against the allowed set and are dropped too
  (also counted in `guard.removed`).
- A cited sequence of >= 2 moves must be legal (rules.validate_line) from the position before or after the
  player's move; otherwise the sentence is dropped (`guard.illegal_variations`).
- Lists are cut to their limits (`guard.truncated`), strings to MAX_TEXT chars.
Malformed JSON is retried once; then, like a missing key or a provider error, the response is
source="rules" so the frontend keeps its rule-based text. The coach never fakes an LLM answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.services.coach.llm import ERR_TIMEOUT, LLMProvider, ProviderError
from app.services.rules import xiangqi as rules

log = logging.getLogger(__name__)

MAX_TOKENS = 16000  # room for always-on thinking (Opus 5.5) plus the short JSON reply
# One deadline for the whole LLM phase (malformed-JSON retry, HF resend without response_format: up to 4 POSTs),
# below the desktop's 90 s SLOW_MS.
COACH_DEADLINE_S = 75.0
MAX_TEXT = 600
LIST_LIMITS = {"did_well": 3, "missed": 3, "questions": 3}
TEXT_FIELDS = ("why_it_matters", "what_to_learn", "next_exercise")
# no word boundaries on purpose: "Xeb2e2" still counts as a move; a false positive only drops a sentence.
# The two squares may be joined or separated ("h2-e2", "h2 e2", "h2→e2", "h2xe2"); matches are normalized to "h2e2".
MOVE_RE = re.compile(r"(?<!\d)([a-i]\d)\s*(?:->|[-–—→x×:]|\s)?\s*([a-i]\d)(?!\d)", re.IGNORECASE)
_PIECE = r"(?:tướng|tuong|sĩ|sỹ|si|tượng|xe|pháo|phao|mã|ma|tốt|tot|binh|[KABENHRCP])"
_ACTION = r"(?:tiến|tien|thoái|thoai|bình|binh|[.=+\-])"
# Traditional notation: piece (VN name or letter), file digit, action, digit; plus Chinese "炮二平五".
TRAD_RE = re.compile(
    rf"(?<![^\W\d_]){_PIECE}\s*\d\s*{_ACTION}\s*\d"
    r"|[车車马馬炮砲相象仕士帅帥将將兵卒俥傌炮][一二三四五六七八九1-9１-９][进進退平][一二三四五六七八九1-9１-９]",
    re.IGNORECASE,
)
SEQ_GAP_RE = re.compile(r"^[\s,;\-–→>]*$")  # what may sit between two moves of one cited line
SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")

Short = Field(default="", max_length=500)

_STR_LIST = {"type": "array", "items": {"type": "string"}}
# Structured output (output_config.format): makes malformed JSON rare; parsing, retry and the guard still run.
FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "did_well": _STR_LIST,
        "missed": _STR_LIST,
        "why_it_matters": {"type": "string"},
        "what_to_learn": {"type": "string"},
        "next_exercise": {"type": "string"},
        "questions": _STR_LIST,
    },
    "required": ["did_well", "missed", "why_it_matters", "what_to_learn", "next_exercise", "questions"],
    "additionalProperties": False,
}


class Risks(BaseModel):
    check: bool
    capture: bool
    counterattack: bool


class SelfAssessmentIn(BaseModel):
    intention: str = Short
    predicted_opponent_reply: str = Field(default="", max_length=10)
    predicted_variations: list[str] = Field(default_factory=list, max_length=5)
    depth: int | None = None
    recognized_risks: Risks | None = None
    position_assessment: Literal["better", "equal", "worse"] | None = None
    skipped: bool = False


class EngineIn(BaseModel):
    """desktop EngineAnalysis (+ optional extras from /engine/evaluate-move)."""

    source: str = "pikafish"
    eval_before_cp: int
    eval_after_cp: int
    best_move: str = Field(default="", max_length=10)
    opponent_best_replies: list[str] = Field(default_factory=list, max_length=10)
    principal_variation: list[str] = Field(default_factory=list, max_length=40)
    threats: Risks
    material_at_risk: bool
    cp_loss: int | None = None
    stable: bool | None = None
    notes: list[str] = Field(default_factory=list, max_length=10)


class CoachRequest(BaseModel):
    board_before: str = Field(max_length=200)  # FEN
    player_move: str = Field(max_length=10)
    move_quality_score: int | None = None
    move_quality_label: str = Field(default="", max_length=100)
    thinking_quality_score: int | None = None
    thinking_components: dict[str, float | None] = Field(default_factory=dict, max_length=10)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    missed_threats: list[str] = Field(default_factory=list, max_length=10)
    self_assessment: SelfAssessmentIn = Field(default_factory=SelfAssessmentIn)
    engine: EngineIn | None = None
    reveal_engine: bool = False


class Feedback(BaseModel):
    did_well: list[str] = []
    missed: list[str] = []
    why_it_matters: str = ""
    what_to_learn: str = ""
    next_exercise: str = ""
    questions: list[str] = []


class GuardStats(BaseModel):
    removed: int = 0
    illegal_variations: int = 0
    truncated: int = 0


class CoachResponse(BaseModel):
    source: Literal["llm", "rules"]
    available: bool
    reason: str | None = None
    feedback: Feedback | None = None
    guard: GuardStats = Field(default_factory=GuardStats)
    model: str | None = None
    provider: str | None = None


SYSTEM_PROMPT = """Bạn là huấn luyện viên tư duy cờ Tướng. Bạn nhận dữ liệu JSON về MỘT nước đi của người chơi.
Quy tắc bắt buộc:
1. Chỉ giải thích dựa trên dữ liệu được cung cấp. Không tự phân tích thế cờ, không bịa nước đi hay biến.
2. Chỉ được nhắc nước đi (dạng tọa độ như b2e2) có trong dữ liệu: nước của người chơi, nước/biến người chơi tự dự đoán{engine_rule}.
3. {reveal_rule}
4. Tách rõ hai việc: đánh giá của engine về nước đi (điểm, mất bao nhiêu centipawn) và đánh giá kỹ năng tư duy (người chơi đã nghĩ đúng/sai gì).
5. Tối đa 3 điểm cần cải thiện. Mỗi nhận xét phải kèm lý do lấy từ dữ liệu.
6. Viết tiếng Việt, ngắn gọn, khích lệ, không phán xét.
Chỉ trả về MỘT đối tượng JSON, không có văn bản nào khác, theo đúng dạng:
{{"did_well": [chuỗi, tối đa 3], "missed": [chuỗi, tối đa 3], "why_it_matters": chuỗi, "what_to_learn": chuỗi,
"next_exercise": chuỗi, "questions": [câu hỏi gợi mở, tối đa 3]}}"""

REVEAL_YES = "Người chơi đã cho phép xem nước của engine; có thể nhắc chúng khi cần để giải thích."
REVEAL_NO = (
    "KHÔNG tiết lộ nước tốt nhất hay biến của engine (bạn cũng không được cung cấp). "
    "Thay vào đó hãy đặt câu hỏi gợi mở để người chơi tự tìm."
)


def build_prompt(req: CoachRequest) -> tuple[str, str]:
    system = SYSTEM_PROMPT.format(
        engine_rule=", và nước/biến của engine" if req.reveal_engine else "",
        reveal_rule=REVEAL_YES if req.reveal_engine else REVEAL_NO,
    )
    data = req.model_dump(exclude={"reveal_engine"})
    data["board_after"] = rules.apply_move(req.board_before, req.player_move)
    if req.engine and not req.reveal_engine:
        # the LLM cannot leak what it never sees; the guard below is the second layer
        for key in ("best_move", "opponent_best_replies", "principal_variation"):
            data["engine"].pop(key)
    return system, "Dữ liệu nước đi:\n" + json.dumps(data, ensure_ascii=False, indent=1)


def _parse(text: str) -> Feedback | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    lists = {k: data.get(k) or [] for k in LIST_LIMITS}
    if not all(isinstance(v, list) for v in lists.values()):
        return None
    return Feedback(
        **{k: [x for x in v if isinstance(x, str)] for k, v in lists.items()},
        **{k: str(data.get(k) or "") for k in TEXT_FIELDS},
    )


def allowed_moves(req: CoachRequest) -> set[str]:
    sa = req.self_assessment
    allowed = {req.player_move, sa.predicted_opponent_reply}
    for v in sa.predicted_variations:
        allowed.update(v.split())
    if req.reveal_engine and req.engine:
        e = req.engine
        allowed.update([e.best_move, *e.opponent_best_replies, *e.principal_variation])
    return {m.strip().lower() for m in allowed if m.strip()}


def _move(m: re.Match[str]) -> str:
    return (m[1] + m[2]).lower()


def _sequences(text: str) -> list[list[str]]:
    """Runs of >= 2 move tokens separated only by spaces/commas/arrows: a cited variation."""
    runs: list[list[str]] = []
    prev_end = None
    for m in MOVE_RE.finditer(text):
        if prev_end is not None and SEQ_GAP_RE.match(text[prev_end : m.start()]):
            runs[-1].append(_move(m))
        else:
            runs.append([_move(m)])
        prev_end = m.end()
    return [r for r in runs if len(r) >= 2]


class _Guard:
    def __init__(self, req: CoachRequest):
        self.allowed = allowed_moves(req)
        self.fens = (req.board_before, rules.apply_move(req.board_before, req.player_move))
        self.stats = GuardStats()

    def _legal(self, seq: list[str]) -> bool:
        return any(rules.validate_line(fen, seq) is None for fen in self.fens)

    def text(self, text: str) -> str:
        kept = []
        for sentence in SENTENCE_RE.split(text.strip()):
            if TRAD_RE.search(sentence) or any(_move(m) not in self.allowed for m in MOVE_RE.finditer(sentence)):
                self.stats.removed += 1
            elif not all(self._legal(seq) for seq in _sequences(sentence)):
                self.stats.illegal_variations += 1
            elif sentence:
                kept.append(sentence)
        out = " ".join(kept)
        if len(out) > MAX_TEXT:
            self.stats.truncated += 1
            out = out[: MAX_TEXT - 1].rstrip() + "…"
        return out

    def items(self, items: list[str], limit: int) -> list[str]:
        cleaned = [t for t in (self.text(i) for i in items) if t]
        if len(cleaned) > limit:
            self.stats.truncated += len(cleaned) - limit
        return cleaned[:limit]


def guard_feedback(req: CoachRequest, fb: Feedback) -> tuple[Feedback, GuardStats]:
    g = _Guard(req)
    out = Feedback(
        **{k: g.items(getattr(fb, k), limit) for k, limit in LIST_LIMITS.items()},
        **{k: g.text(getattr(fb, k)) for k in TEXT_FIELDS},
    )
    return out, g.stats


NO_PROVIDER = "Chưa cấu hình LLM (XQC_LLM_API_KEY hoặc XQC_HF_TOKEN)"


def _rules(
    reason: str, available: bool, provider: LLMProvider | None = None, guard: GuardStats | None = None
) -> CoachResponse:
    return CoachResponse(
        source="rules",
        available=available,
        reason=reason,
        model=provider.model if provider else None,
        provider=provider.name if provider else None,
        guard=guard or GuardStats(),
    )


async def coach_move(req: CoachRequest, provider: LLMProvider | None) -> CoachResponse:
    """Raises rules.FenError / rules.IllegalMoveError on a bad position or move (checked before any LLM call)."""
    rules.apply_move(req.board_before, req.player_move)
    if provider is None:
        return _rules(NO_PROVIDER + "; dùng nhận xét theo quy tắc.", available=False)
    system, user = build_prompt(req)
    fb = None
    try:
        async with asyncio.timeout(COACH_DEADLINE_S):
            for attempt in range(2):
                if attempt:
                    user += "\n\nLần trước bạn không trả về JSON hợp lệ. Chỉ trả về đúng một đối tượng JSON."
                fb = _parse(await provider.complete(system, user, MAX_TOKENS, FEEDBACK_SCHEMA))
                if fb is not None:
                    break
    except ProviderError as e:
        log.warning("coach provider error", extra={"provider": provider.name, "reason": str(e)})
        return _rules(str(e), available=False, provider=provider)
    except TimeoutError:
        log.warning("coach provider error", extra={"provider": provider.name, "reason": "deadline"})
        return _rules(ERR_TIMEOUT, available=False, provider=provider)
    except Exception as e:  # a provider bug must not turn into a 500; the type only, the message may hold data
        log.warning("coach provider failure", extra={"provider": provider.name, "error_type": type(e).__name__})
        return _rules("Lỗi không mong đợi khi gọi LLM; dùng nhận xét theo quy tắc.", available=False, provider=provider)
    if fb is None:
        return _rules("LLM trả về dữ liệu không hợp lệ; dùng nhận xét theo quy tắc.", True, provider)

    fb, stats = guard_feedback(req, fb)
    log.info("coach feedback", extra={"provider": provider.name, "model": provider.model, **stats.model_dump()})
    if not any(getattr(fb, k) for k in (*LIST_LIMITS, *TEXT_FIELDS)):
        return _rules("Nhận xét của LLM bị bộ lọc loại hết; dùng nhận xét theo quy tắc.", True, provider, stats)
    return CoachResponse(
        source="llm", available=True, feedback=fb, guard=stats, model=provider.model, provider=provider.name
    )
