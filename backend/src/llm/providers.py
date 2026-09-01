"""LLM provider implementations."""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional, Protocol

from ..errors.types import CODE_LLM_ERROR, LLMAPIError
from .events import (
    DoneEvent,
    ErrorEvent,
    LLMEvent,
    Message,
    TextDeltaEvent,
    ToolCallEvent,
)
from .stream_buffer import StreamBuffer

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    model: str

    def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMEvent]: ...


_RETRYABLE_ERROR_NAMES = {
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
    "TimeoutError",
    "NetworkError",
    "ServiceUnavailable",
}


def _is_retryable(exc: BaseException) -> bool:
    name = exc.__class__.__name__
    if name in _RETRYABLE_ERROR_NAMES:
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status >= 500


class OpenAIProvider:
    """OpenAI or OpenAI-compatible chat completion provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        name: str = "openai",
    ) -> None:
        from openai import AsyncOpenAI

        if not api_key:
            raise LLMAPIError(
                message="未配置 API Key，请设置环境变量 LLM_API_KEY",
                code=CODE_LLM_ERROR,
                provider=name,
                retryable=False,
                suggestions=["复制 .env.example 为 .env 并填写 LLM_API_KEY"],
            )

        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**client_kwargs)
        self.model = model
        self.name = name
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMEvent]:
        params: dict = {
            "model": self.model,
            "messages": [
                m.to_api_dict(include_reasoning_content=self.name == "deepseek")
                for m in messages
            ],
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"
        params.update(kwargs)

        buffer = StreamBuffer()
        stop_reason = "stop"
        usage: dict = {}
        reasoning_parts: list[str] = []

        try:
            stream = await self.client.chat.completions.create(**params)
            async for chunk in stream:
                if chunk.usage is not None:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                reasoning_content = getattr(delta, "reasoning_content", None)
                if reasoning_content:
                    reasoning_parts.append(reasoning_content)

                if delta is not None and delta.content:
                    buffer.add_text_delta(delta.content)
                    yield TextDeltaEvent(text=delta.content)

                if delta is not None and delta.tool_calls:
                    for tc in delta.tool_calls:
                        fn = tc.function
                        buffer.add_tool_call_delta(
                            index=tc.index,
                            call_id=tc.id,
                            name=fn.name if fn else None,
                            arguments=fn.arguments if fn else None,
                        )

                if choice.finish_reason:
                    stop_reason = choice.finish_reason

        except Exception as exc:  # noqa: BLE001
            retryable = _is_retryable(exc)
            logger.warning(
                "LLM call failed provider=%s retryable=%s: %s",
                self.name,
                retryable,
                exc,
            )
            yield ErrorEvent(message=f"{exc.__class__.__name__}: {exc}", retryable=retryable)
            return

        partial_tool_calls = buffer.has_incomplete_tool_calls()
        complete_tool_calls = (
            [] if partial_tool_calls else buffer.get_complete_tool_calls()
        )
        for call in complete_tool_calls:
            yield ToolCallEvent(
                id=call["id"], name=call["name"], arguments=call["arguments"]
            )

        yield DoneEvent(
            stop_reason=stop_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
            partial_tool_calls=partial_tool_calls,
        )


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider using its OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            name="deepseek",
        )
