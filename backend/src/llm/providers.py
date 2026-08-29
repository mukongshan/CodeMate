"""LLM Provider 实现。

对应功能设计 06-LLM接口层 4.1/4.2 节。

DeepSeek 兼容 OpenAI 协议，所以只需要换 ``base_url`` 复用同一个 ``AsyncOpenAI``
客户端，不必单独实现协议解析（06 号文档 4.2 节）。
"""

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
    """Provider 协议。上层只依赖这个形状，不关心具体厂商。"""

    model: str

    def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMEvent]: ...


# 可重试的 OpenAI 异常类名（06 号文档 5.1 节的分类）
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
    """按异常类名判断是否可重试。

    用类名而不是 isinstance：openai SDK 的异常层级在不同版本间有调整，
    按名字匹配对版本更宽容，而且和 06 号文档 5.2 节 ``should_retry`` 的写法一致。
    """
    name = exc.__class__.__name__
    if name in _RETRYABLE_ERROR_NAMES:
        return True
    # 5xx 一律可重试，4xx 不重试
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status >= 500


class OpenAIProvider:
    """OpenAI / 任何兼容 OpenAI 协议的服务。"""

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
                message="未配置 API Key，请设置环境变量 OPENAI_API_KEY 或 DEEPSEEK_API_KEY",
                code=CODE_LLM_ERROR,
                provider=name,
                retryable=False,
                suggestions=["复制 .env.example 为 .env 并填入 API Key"],
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
            "messages": [m.to_api_dict() for m in messages],
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            # 不加这个，流式响应的 usage 永远是 None，token 统计拿不到数
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"
        # 允许调用方覆盖（子 Agent 收尾时要传 tool_choice="none"，
        # 所以这里不能把 tool_choice 写死）
        params.update(kwargs)

        buffer = StreamBuffer()
        stop_reason = "stop"
        usage: dict = {}

        try:
            stream = await self.client.chat.completions.create(**params)
            async for chunk in stream:
                # 带 include_usage 时最后一个 chunk 的 choices 是空列表
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

        except Exception as exc:  # noqa: BLE001 - 统一转成 ErrorEvent 交给重试层
            retryable = _is_retryable(exc)
            logger.warning(
                "LLM 调用失败 provider=%s retryable=%s: %s",
                self.name,
                retryable,
                exc,
            )
            yield ErrorEvent(message=f"{exc.__class__.__name__}: {exc}", retryable=retryable)
            return

        # 参数拼接完成后再一次性下发工具调用事件
        for call in buffer.get_complete_tool_calls():
            yield ToolCallEvent(
                id=call["id"], name=call["name"], arguments=call["arguments"]
            )

        yield DoneEvent(stop_reason=stop_reason, usage=usage)


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek。兼容 OpenAI 协议，只换 base_url 和默认模型。"""

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
