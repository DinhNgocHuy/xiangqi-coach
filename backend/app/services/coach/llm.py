"""LLM provider abstraction. AnthropicProvider uses the official `anthropic` SDK (AsyncAnthropic, built on httpx2)."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import anthropic

from app.core.config import Settings

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
TIMEOUT_S = 60.0
MAX_RETRIES = 2  # SDK retries connection errors, 408/409/429/5xx with backoff
# Opus 5.5 always thinks: never send `thinking` disabled/budget or temperature (400). Effort is the only knob;
# "medium" is the documented starting point, measure before lowering.
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # needed for fallbacks="default" (re-run a refusal server-side)


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
            raise ProviderError("API key của LLM không hợp lệ hoặc không có quyền.") from None
        except anthropic.RateLimitError:
            raise ProviderError("Đã vượt giới hạn tần suất gọi LLM, thử lại sau.") from None
        except anthropic.APIStatusError as e:
            log.warning("llm http error", extra={"status": e.status_code, "error_type": getattr(e, "type", None)})
            if e.status_code >= 500:  # includes 529 overloaded
                raise ProviderError("Dịch vụ LLM đang quá tải hoặc gặp lỗi, thử lại sau.") from None
            raise ProviderError(f"LLM từ chối yêu cầu (HTTP {e.status_code}).") from None
        except anthropic.APITimeoutError:  # subclass of APIConnectionError: must come first
            raise ProviderError("LLM không phản hồi kịp (hết thời gian chờ).") from None
        except anthropic.APIConnectionError:
            raise ProviderError("Không kết nối được tới LLM.") from None
        if response.stop_reason == "refusal":  # whole fallback chain refused; check before reading content
            raise ProviderError("LLM từ chối trả lời yêu cầu này.")
        return "".join(b.text for b in response.content if b.type == "text")


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
    """None when no key is configured: the coach is disabled and the frontend keeps its rule-based text."""
    if not settings.llm_api_key:
        return None
    return AnthropicProvider(settings.llm_api_key, settings.llm_model or DEFAULT_MODEL)
