"""LLM provider abstraction.

AnthropicProvider uses the official `anthropic` SDK (AsyncAnthropic, built on httpx2). HuggingFaceProvider calls the
OpenAI-compatible Hugging Face Inference Providers router with httpx2 directly (already installed via anthropic;
`huggingface_hub` would add ~6 MB of wheels incl. the native hf_xet for one POST).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Protocol

import anthropic
import httpx2

from app.core.config import Settings

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
TIMEOUT_S = 60.0
MAX_RETRIES = 2  # SDK retries connection errors, 408/409/429/5xx with backoff
# Opus 5.5 always thinks: never send `thinking` disabled/budget or temperature (400). Effort is the only knob;
# "medium" is the documented starting point, measure before lowering.
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # needed for fallbacks="default" (re-run a refusal server-side)


HF_URL = "https://router.huggingface.co/v1/chat/completions"
# Non-thinking instruct model, strong multilingual (incl. Vietnamese); every router provider serving it supports
# structured output (GET https://router.huggingface.co/v1/models, 2026-11-27).
HF_DEFAULT_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
HF_CONNECT_TIMEOUT_S = 10.0
HF_MAX_TOKENS = 2048  # the JSON feedback is short; the default model does not think
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)  # reasoning models may inline their thoughts

ERR_AUTH = "API key của LLM không hợp lệ hoặc không có quyền."
ERR_RATE = "Đã vượt giới hạn tần suất gọi LLM, thử lại sau."
ERR_SERVER = "Dịch vụ LLM đang quá tải hoặc gặp lỗi, thử lại sau."
ERR_TIMEOUT = "LLM không phản hồi kịp (hết thời gian chờ)."
ERR_CONNECT = "Không kết nối được tới LLM."
ERR_HF_AUTH = "Token Hugging Face không hợp lệ hoặc thiếu quyền Inference Providers."
ERR_HF_CREDITS = "Đã hết hạn mức Hugging Face (credits Inference Providers); nạp thêm hoặc chờ kỳ sau."


class ProviderError(Exception):
    """User-facing (Vietnamese) reason; never contains the key or the prompt."""


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None = None) -> str: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, http_client: Any = None):
        # http_client: tests pass anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(...))
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=TIMEOUT_S, max_retries=MAX_RETRIES, http_client=http_client
        )
        self.model = model

    def __repr__(self) -> str:  # keep the key out of logs/tracebacks
        return f"AnthropicProvider(model={self.model!r})"

    async def aclose(self) -> None:
        await self._client.close()

    async def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None = None) -> str:
        output_config: dict[str, Any] = {"effort": EFFORT}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        log.debug("llm request", extra={"model": self.model, "system_chars": len(system), "user_chars": len(user)})
        try:
            response = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise ProviderError(ERR_AUTH) from None
        except anthropic.RateLimitError:
            raise ProviderError(ERR_RATE) from None
        except anthropic.APIStatusError as e:
            log.warning("llm http error", extra={"status": e.status_code, "error_type": getattr(e, "type", None)})
            if e.status_code >= 500:  # includes 529 overloaded
                raise ProviderError(ERR_SERVER) from None
            raise ProviderError(f"LLM từ chối yêu cầu (HTTP {e.status_code}).") from None
        except anthropic.APITimeoutError:  # subclass of APIConnectionError: must come first
            raise ProviderError(ERR_TIMEOUT) from None
        except anthropic.APIConnectionError:
            raise ProviderError(ERR_CONNECT) from None
        if response.stop_reason == "refusal":  # whole fallback chain refused; check before reading content
            raise ProviderError("LLM từ chối trả lời yêu cầu này.")
        return "".join(b.text for b in response.content if b.type == "text")


class HuggingFaceProvider:
    """Hugging Face Inference Providers, OpenAI-compatible chat completions. No client retries: the router already
    fails over to another provider serving the model."""

    name = "huggingface"

    def __init__(self, token: str, model: str = HF_DEFAULT_MODEL, transport: Any = None):
        # transport: tests pass httpx2.MockTransport(...)
        self._client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx2.Timeout(TIMEOUT_S, connect=HF_CONNECT_TIMEOUT_S),
            transport=transport,
        )
        self.model = model

    def __repr__(self) -> str:  # keep the token out of logs/tracebacks
        return f"HuggingFaceProvider(model={self.model!r})"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, body: dict[str, Any]) -> httpx2.Response:
        try:
            async with asyncio.timeout(TIMEOUT_S):  # total budget; httpx2 timeouts are per phase
                return await self._client.post(HF_URL, json=body)
        except (TimeoutError, httpx2.TimeoutException):  # TimeoutException is a TransportError: must come first
            raise ProviderError(ERR_TIMEOUT) from None
        except httpx2.RequestError:  # transport errors, also DecodingError / TooManyRedirects
            raise ProviderError(ERR_CONNECT) from None

    async def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None = None) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": min(max_tokens, HF_MAX_TOKENS),
            "stream": False,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "coach_feedback", "schema": schema, "strict": True},
            }
        log.debug("llm request", extra={"model": self.model, "system_chars": len(system), "user_chars": len(user)})
        r = await self._post(body)
        if r.status_code in (400, 422) and "response_format" in body:
            # the chosen model/provider may not support structured output: the prompt + parse/retry still apply
            log.warning("llm rejected response_format", extra={"status": r.status_code, "error": _error_message(r)})
            del body["response_format"]
            r = await self._post(body)
        if r.status_code != 200:
            log.warning("llm http error", extra={"status": r.status_code})
            if r.status_code in (401, 403):
                raise ProviderError(ERR_HF_AUTH)
            if r.status_code == 402:
                raise ProviderError(ERR_HF_CREDITS)
            if r.status_code == 429:
                raise ProviderError(ERR_RATE)
            if r.status_code >= 500:
                raise ProviderError(ERR_SERVER)
            raise ProviderError(f"LLM từ chối yêu cầu (HTTP {r.status_code}).")
        try:
            content = r.json()["choices"][0]["message"]["content"]
        except (ValueError, LookupError, TypeError):
            return ""  # treated like malformed JSON by the coach (one retry, then rule-based fallback)
        return _strip_think(content) if isinstance(content, str) else ""


def _error_message(r: httpx2.Response) -> str:
    """Provider's error text for the log, truncated (OpenAI-style {"error": {"message": ...}} or {"error": "..."})."""
    try:
        err = r.json().get("error")
    except (ValueError, AttributeError):
        return r.text[:200]
    return str(err.get("message") if isinstance(err, dict) else err)[:200]


def _strip_think(text: str) -> str:
    text = THINK_RE.sub("", text)
    text = text.rpartition("</think>")[2]  # unopened block: thoughts before the tag
    return text.partition("<think>")[0]  # unclosed block (cut off by max_tokens)


class FakeProvider:
    """Test double: returns queued replies in order; an Exception in the queue is raised."""

    name = "fake"
    model = "fake"

    def __init__(self, *replies: str | Exception):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []
        self.schemas: list[dict[str, Any] | None] = []

    async def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None = None) -> str:
        self.calls.append((system, user))
        self.schemas.append(schema)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make_provider(settings: Settings) -> LLMProvider | None:
    """None when the selected provider has no key: the coach is disabled and the frontend keeps its rule-based text.
    Auto (XQC_LLM_PROVIDER unset): anthropic if XQC_LLM_API_KEY, else huggingface if XQC_HF_TOKEN, else none."""
    kind = settings.llm_provider or ("anthropic" if settings.llm_api_key else "huggingface")
    if kind == "anthropic" and settings.llm_api_key:
        return AnthropicProvider(settings.llm_api_key, settings.llm_model or DEFAULT_MODEL)
    if kind == "huggingface" and settings.hf_token:
        return HuggingFaceProvider(settings.hf_token, settings.hf_model or HF_DEFAULT_MODEL)
    return None
