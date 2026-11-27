import asyncio
import json
from pathlib import Path

import anthropic
import httpx2
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.coach.coach import FEEDBACK_SCHEMA, CoachRequest, coach_move
from app.services.coach.llm import AnthropicProvider, FakeProvider, ProviderError, make_provider
from app.services.rules.xiangqi import START_FEN

ENGINE = {
    "eval_before_cp": 20,
    "eval_after_cp": -40,
    "best_move": "h2e2",
    "opponent_best_replies": ["h7e7", "b9c7"],
    "principal_variation": ["h7e7", "h0g2"],
    "threats": {"check": False, "capture": False, "counterattack": False},
    "material_at_risk": False,
    "cp_loss": 60,
}


def _req(**kw) -> CoachRequest:
    data = {
        "board_before": START_FEN,
        "player_move": "b2e2",
        "move_quality_label": "Thiếu chính xác",
        "strengths": ["Bạn đã dự đoán đúng phản ứng của đối thủ (h9g7)."],
        "self_assessment": {"predicted_opponent_reply": "h9g7", "predicted_variations": ["h9g7 b0c2"]},
        "engine": ENGINE,
    }
    return CoachRequest(**(data | kw))


def _answer(**kw) -> str:
    base = {
        "did_well": ["Bạn dự đoán h9g7 là hợp lý."],
        "missed": ["Bạn chưa xét nguy cơ bị phản công."],
        "why_it_matters": "Engine đánh giá nước đi mất 60 cp.",
        "what_to_learn": "Tìm nước đáp mạnh nhất của đối thủ.",
        "next_exercise": "Giải 3 thế cờ về Pháo đầu.",
        "questions": ["Đối thủ có nước nào mạnh hơn h9g7 không?"],
    }
    return json.dumps(base | kw, ensure_ascii=False)


def _run(req: CoachRequest, *replies):
    provider = FakeProvider(*replies)
    return asyncio.run(coach_move(req, provider)), provider


def test_valid_output_passes_and_engine_moves_not_sent() -> None:
    res, p = _run(_req(), _answer())
    assert res.source == "llm" and res.available
    assert res.feedback.did_well == ["Bạn dự đoán h9g7 là hợp lý."]
    assert res.guard.removed == res.guard.illegal_variations == res.guard.truncated == 0
    system, user = p.calls[0]
    assert "KHÔNG tiết lộ" in system and p.schemas[0] == FEEDBACK_SCHEMA
    assert "h7e7" not in user and "h2e2" not in user and "b2e2" in user


def test_invented_move_sentence_removed() -> None:
    res, _ = _run(_req(), _answer(missed=["Bạn nên đi C3C4 trước. Hãy kiểm tra an toàn Tướng."]))
    assert res.feedback.missed == ["Hãy kiểm tra an toàn Tướng."]
    assert res.guard.removed == 1


def test_separated_and_traditional_notation_removed() -> None:
    invented = ["h2-e2", "h2 e2", "h2→e2", "h2xe2", "H2 - E2"]
    trad = ["Pháo 2 bình 5", "Mã 8 tiến 7", "Xe 1 thoái 2", "phao 2 binh 5", "C2=5", "C2.5", "H8+7", "R1-2", "炮二平五"]
    for move in invented + trad:
        res, _ = _run(_req(), _answer(missed=[f"Bạn nên đi {move} trước. Xe của bạn cần ra sớm."]))
        assert res.feedback.missed == ["Xe của bạn cần ra sớm."], move
        assert res.guard.removed == 1, move
    # Allowed moves written with separators are kept; plain prose about pieces is not over-dropped.
    ok = "Nước b2-e2 của bạn hợp lý. Bạn đoán đúng h9 g7. Pháo và Mã của bạn phối hợp tốt. Xe 2 quân rất mạnh."
    res, _ = _run(_req(), _answer(why_it_matters=ok))
    assert res.feedback.why_it_matters == ok and res.guard.removed == 0


def test_engine_move_removed_unless_revealed() -> None:
    text = "Engine chọn h2e2 tốt hơn. Đối thủ sẽ đáp h7e7."
    hidden, _ = _run(_req(), _answer(why_it_matters=text))
    assert hidden.feedback.why_it_matters == "" and hidden.guard.removed == 2
    shown, p = _run(_req(reveal_engine=True), _answer(why_it_matters=text))
    assert shown.feedback.why_it_matters == text and shown.guard.removed == 0
    assert "h7e7" in p.calls[0][1]


def test_illegal_variation_removed_legal_kept() -> None:
    req = _req(self_assessment={"predicted_opponent_reply": "h9g7", "predicted_variations": ["h9g7 a0a5"]})
    res, _ = _run(req, _answer(what_to_learn="Biến h9g7 a0a5 của bạn. Biến b2e2 → h9g7 đúng hướng."))
    assert res.feedback.what_to_learn == "Biến b2e2 → h9g7 đúng hướng."
    assert res.guard.illegal_variations == 1 and res.guard.removed == 0


def test_malformed_json_retries_then_falls_back() -> None:
    res, p = _run(_req(), "không phải JSON", "```json\n" + _answer() + "\n```")
    assert res.source == "llm" and len(p.calls) == 2 and "JSON hợp lệ" in p.calls[1][1]
    res, p = _run(_req(), "{oops", '{"did_well": "not a list"}')
    assert res.source == "rules" and res.available and res.feedback is None and len(p.calls) == 2


def test_provider_error_and_no_key_fall_back_to_rules() -> None:
    res, _ = _run(_req(), ProviderError("LLM không phản hồi kịp."))
    assert (res.source, res.available, res.reason) == ("rules", False, "LLM không phản hồi kịp.")
    res = asyncio.run(coach_move(_req(), None))
    assert res.source == "rules" and not res.available and "XQC_LLM_API_KEY" in res.reason
    assert make_provider(Settings()) is None


def test_list_and_text_limits() -> None:
    res, _ = _run(_req(), _answer(did_well=[f"Điểm {i}." for i in range(5)], next_exercise="x" * 2000))
    assert res.feedback.did_well == ["Điểm 0.", "Điểm 1.", "Điểm 2."]
    assert len(res.feedback.next_exercise) == 600
    assert res.guard.truncated == 3


def test_everything_removed_falls_back() -> None:
    bad = "Đi a0a1."
    res, _ = _run(_req(), json.dumps({"did_well": [bad], "missed": [bad], "why_it_matters": bad}))
    assert res.source == "rules" and res.available and res.guard.removed == 3


def _anthropic(handler) -> AnthropicProvider:
    transport = httpx2.MockTransport(handler)
    provider = AnthropicProvider("sk-secret", "claude-opus-5-5", http_client=anthropic.DefaultAsyncHttpxClient(transport=transport))
    provider._client = provider._client.with_options(max_retries=0)  # no backoff sleeps in tests
    return provider


def _message(stop_reason: str = "end_turn", content=None) -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content if content is not None else [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": _answer()},
        ],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def test_anthropic_provider_request_shape() -> None:
    seen = {}

    def ok(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx2.Response(200, json=_message())

    out = asyncio.run(_anthropic(ok).complete("S", "U", 16000, FEEDBACK_SCHEMA))
    assert json.loads(out)["did_well"]  # only the text block is returned, thinking block skipped
    body, headers = seen["body"], seen["headers"]
    assert body["model"] == "claude-opus-5-5" and body["system"] == "S" and body["max_tokens"] == 16000
    assert body["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": FEEDBACK_SCHEMA}}
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert "temperature" not in body and "thinking" not in body
    assert any("sk-secret" in v for v in headers.values())  # SDK 2.x sends it as Authorization
    assert "sk-secret" not in repr(_anthropic(ok))


def _raises(provider: AnthropicProvider, needle: str) -> None:
    try:
        asyncio.run(provider.complete("S", "U", 10))
    except ProviderError as e:
        assert needle in str(e) and "sk-secret" not in str(e)
    else:
        raise AssertionError("expected ProviderError")


def test_anthropic_provider_refusal_and_errors() -> None:
    refusal = _message("refusal", [{"type": "text", "text": "{}"}])
    _raises(_anthropic(lambda r: httpx2.Response(200, json=refusal)), "từ chối trả lời")

    def fail(status: int, kind: str):
        return lambda r: httpx2.Response(status, json={"type": "error", "error": {"type": kind, "message": "x"}})

    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    def offline(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    cases = [
        (fail(401, "authentication_error"), "API key"),
        (fail(403, "permission_error"), "API key"),
        (fail(429, "rate_limit_error"), "tần suất"),
        (fail(529, "overloaded_error"), "quá tải"),
        (fail(500, "api_error"), "quá tải"),
        (fail(400, "invalid_request_error"), "HTTP 400"),
        (timeout, "hết thời gian"),
        (offline, "Không kết nối"),
    ]
    for handler, needle in cases:
        _raises(_anthropic(handler), needle)


def test_api_status_and_feedback(tmp_path: Path) -> None:
    app = create_app(Settings(db_path=tmp_path / "coach.db"))
    body = _req().model_dump()
    with TestClient(app) as client:
        assert client.get("/coach/status").json()["available"] is False
        r = client.post("/coach/move-feedback", json=body)
        assert r.status_code == 200 and r.json()["source"] == "rules" and r.json()["available"] is False
        app.state.coach_provider = FakeProvider(_answer())
        assert client.get("/coach/status").json() == {"available": True, "provider": "fake", "model": "fake", "reason": None}
        r = client.post("/coach/move-feedback", json=body)
        assert r.json()["source"] == "llm" and r.json()["feedback"]["did_well"]
        assert client.post("/coach/move-feedback", json=body | {"player_move": "a0a5"}).status_code == 400
