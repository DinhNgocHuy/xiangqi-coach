import asyncio
import json
from pathlib import Path

import anthropic
import httpx2
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.coach.coach import FEEDBACK_SCHEMA, CoachRequest, coach_move
from app.services.coach import coach, llm
from app.services.coach.llm import (
    HF_URL,
    AnthropicProvider,
    FakeProvider,
    HuggingFaceProvider,
    ProviderError,
    make_provider,
)
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
    assert "XQC_HF_TOKEN" in res.reason and res.provider is None
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


def _raises(provider, needle: str) -> None:
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


def test_make_provider_selection() -> None:
    both = {"llm_api_key": "sk-secret", "hf_token": "hf_secret"}
    assert isinstance(make_provider(Settings(**both)), AnthropicProvider)  # auto: Anthropic key wins
    hf = make_provider(Settings(hf_token="hf_secret"))
    assert isinstance(hf, HuggingFaceProvider) and hf.model == llm.HF_DEFAULT_MODEL
    assert make_provider(Settings(**both, llm_provider="huggingface", hf_model="m:fastest")).model == "m:fastest"
    assert make_provider(Settings(**both, llm_provider="none")) is None
    assert make_provider(Settings(llm_api_key="sk-secret", llm_provider="huggingface")) is None  # selected but no token
    assert make_provider(Settings(hf_token="hf_secret", llm_provider="anthropic")) is None


def _completion(content) -> dict:
    return {"id": "c1", "object": "chat.completion", "model": "m", "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


def _hf(handler) -> HuggingFaceProvider:
    return HuggingFaceProvider("hf_secret", "Qwen/Qwen3-235B-A22B-Instruct-2507", transport=httpx2.MockTransport(handler))


def test_hf_provider_request_shape_and_parse() -> None:
    seen = []

    def ok(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_completion("<think>hmm</think>" + _answer()))

    out = asyncio.run(_hf(ok).complete("S", "U", 16000, FEEDBACK_SCHEMA))
    assert json.loads(out)["did_well"]  # inline <think> block stripped
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == HF_URL == "https://router.huggingface.co/v1/chat/completions" and req.method == "POST"
    assert req.headers["authorization"] == "Bearer hf_secret"
    assert body["model"] == "Qwen/Qwen3-235B-A22B-Instruct-2507" and body["max_tokens"] == 2048  # capped
    assert body["messages"] == [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    assert body["response_format"] == {
        "type": "json_schema", "json_schema": {"name": "coach_feedback", "schema": FEEDBACK_SCHEMA, "strict": True}}
    asyncio.run(_hf(ok).complete("S", "U", 10))
    assert "response_format" not in json.loads(seen[1].content)
    assert "hf_secret" not in repr(_hf(ok))


def test_hf_provider_strips_unclosed_think_blocks() -> None:
    for content in ("thoughts</think>" + _answer(), _answer() + "<think>cut off by max_tok",
                    "<think>a</think>" + _answer() + "<think>b"):
        out = asyncio.run(_hf(lambda r, c=content: httpx2.Response(200, json=_completion(c))).complete("S", "U", 10))
        assert json.loads(out)["did_well"], content


def test_hf_provider_structured_output_unsupported_retries_without_it(caplog) -> None:
    bodies = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        if "response_format" in bodies[-1]:
            return httpx2.Response(400, json={"error": {"message": "response_format not supported" + "x" * 500}})
        return httpx2.Response(200, json=_completion(_answer()))

    assert json.loads(asyncio.run(_hf(handler).complete("S", "U", 10, FEEDBACK_SCHEMA)))["questions"]
    assert len(bodies) == 2 and "response_format" not in bodies[1]
    logged = [r.error for r in caplog.records if r.getMessage() == "llm rejected response_format"]
    assert logged == ["response_format not supported" + "x" * 171]  # truncated to 200 chars


def test_hf_provider_errors(monkeypatch) -> None:
    def status(code: int):
        return lambda r: httpx2.Response(code, json={"error": "x"})

    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("slow", request=request)

    def offline(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    cases = [
        (status(401), "Token Hugging Face"),
        (status(403), "thiếu quyền Inference Providers"),
        (status(402), "hết hạn mức Hugging Face"),
        (status(429), "tần suất"),
        (status(503), "quá tải"),
        (status(404), "HTTP 404"),
        (timeout, "hết thời gian"),
        (offline, "Không kết nối"),
        (lambda r: (_ for _ in ()).throw(httpx2.DecodingError("bad gzip", request=r)), "Không kết nối"),
        (lambda r: (_ for _ in ()).throw(httpx2.TooManyRedirects("loop", request=r)), "Không kết nối"),
    ]
    for handler, needle in cases:
        _raises(_hf(handler), needle)

    async def slow(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(1)
        return httpx2.Response(200, json=_completion(_answer()))

    monkeypatch.setattr(llm, "TIMEOUT_S", 0.05)  # total-time budget, independent of httpx2 per-phase timeouts
    _raises(_hf(slow), "hết thời gian")


def test_hf_provider_unreadable_body_returns_empty() -> None:
    for resp in (httpx2.Response(200, text="<html>"), httpx2.Response(200, json={"choices": []}),
                 httpx2.Response(200, json=_completion(None))):
        assert asyncio.run(_hf(lambda r, resp=resp: resp).complete("S", "U", 10)) == ""


def test_coach_end_to_end_with_hf_provider(tmp_path: Path) -> None:
    replies = iter(["không phải JSON", _answer(why_it_matters="Engine chọn h2e2 tốt hơn. Mất 60 cp.")])
    app = create_app(Settings(db_path=tmp_path / "coach.db"))
    provider = app.state.coach_provider = _hf(lambda r: httpx2.Response(200, json=_completion(next(replies))))
    with TestClient(app) as client:
        status = client.get("/coach/status").json()
        assert status == {"available": True, "provider": "huggingface",
                          "model": "Qwen/Qwen3-235B-A22B-Instruct-2507", "reason": None}
        r = client.post("/coach/move-feedback", json=_req().model_dump()).json()
    assert r["source"] == "llm" and r["provider"] == "huggingface" and r["model"] == status["model"]
    assert r["feedback"]["why_it_matters"] == "Mất 60 cp." and r["guard"]["removed"] == 1  # guard still applies
    assert provider._client.is_closed  # lifespan shutdown closes the cached provider's HTTP client


class _Slow:
    name, model = "slow", "slow"

    async def complete(self, system, user, max_tokens, schema=None) -> str:
        await asyncio.sleep(1)
        return _answer()


class _Buggy:
    name, model = "buggy", "buggy"

    async def complete(self, system, user, max_tokens, schema=None) -> str:
        raise KeyError("secret prompt text")


def test_coach_overall_deadline_and_unexpected_errors_fall_back(monkeypatch, caplog) -> None:
    monkeypatch.setattr(coach, "COACH_DEADLINE_S", 0.05)
    res = asyncio.run(coach_move(_req(), _Slow()))
    assert (res.source, res.available, res.provider) == ("rules", False, "slow") and "hết thời gian" in res.reason
    res = asyncio.run(coach_move(_req(), _Buggy()))
    assert (res.source, res.available) == ("rules", False) and "không mong đợi" in res.reason
    failures = [r for r in caplog.records if r.getMessage() == "coach provider failure"]
    assert failures and failures[0].error_type == "KeyError"
    assert not any("secret prompt text" in str(r.__dict__) for r in caplog.records)
