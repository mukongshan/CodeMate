"""LLM 客户端：Provider + 指数退避重试。

对应功能设计 06-LLM接口层 5.2 节。

不实现响应缓存（06 号文档六节标注为非首版必需）：默认 temperature=0.7，
缓存命中率本身就低，而 Agent 每轮上下文都在增长，键几乎不会重复。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator, Optional

from ..errors.types import CODE_LLM_ERROR, LLMAPIError
from .events import DoneEvent, ErrorEvent, LLMEvent, Message, TextDeltaEvent
from .providers import DeepSeekProvider, LLMProvider, OpenAIProvider

logger = logging.getLogger(__name__)


class RetryPolicy:
    """指数退避策略（06 号文档 5.2 节）。"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def get_delay(self, attempt: int) -> float:
        """第 attempt 次重试前的等待秒数：1s, 2s, 4s …，上限 max_delay。"""
        return min(self.base_delay * (2**attempt), self.max_delay)


class LLMClient:
    """统一入口，对上层屏蔽重试细节。"""

    def __init__(
        self, provider: LLMProvider, retry_policy: Optional[RetryPolicy] = None
    ) -> None:
        self.provider = provider
        self.retry_policy = retry_policy or RetryPolicy()

    @property
    def model(self) -> str:
        return self.provider.model

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMEvent]:
        """流式对话，可重试错误对调用方不可见。

        一个容易踩的坑：重试意味着整个请求从头重来，如果上一次尝试已经吐了一些
        ``text_delta`` 给前端，重试后会重复吐一遍，UI 上就是文字重复。所以这里
        **只在还没产出任何文本时才重试**——已经开始输出的请求失败了就直接把错误
        传出去，让用户看到一次不完整的回答比看到重复拼接的乱码好。
        """
        attempt = 0

        while True:
            produced_text = False
            error_event: Optional[ErrorEvent] = None

            try:
                async for event in self.provider.chat(messages, tools, **kwargs):
                    if isinstance(event, ErrorEvent):
                        error_event = event
                        break
                    if isinstance(event, TextDeltaEvent):
                        produced_text = True
                    yield event
                    if isinstance(event, DoneEvent):
                        return
            except Exception as exc:  # noqa: BLE001
                error_event = ErrorEvent(
                    message=f"{exc.__class__.__name__}: {exc}", retryable=False
                )

            if error_event is None:
                # 流正常结束但没有 DoneEvent，当成一次完成，避免死循环
                return

            can_retry = (
                error_event.retryable
                and not produced_text
                and attempt < self.retry_policy.max_retries
            )
            if not can_retry:
                raise LLMAPIError(
                    message=error_event.message,
                    code=CODE_LLM_ERROR,
                    provider=getattr(self.provider, "name", "unknown"),
                    retryable=error_event.retryable,
                    suggestions=(
                        ["稍后重试", "检查网络连接与 API Key 配额"]
                        if error_event.retryable
                        else ["检查 API Key 与模型名是否正确"]
                    ),
                )

            delay = self.retry_policy.get_delay(attempt)
            attempt += 1
            logger.warning(
                "LLM 调用失败，%.1fs 后重试（第 %d/%d 次）: %s",
                delay,
                attempt,
                self.retry_policy.max_retries,
                error_event.message,
            )
            await asyncio.sleep(delay)

    @staticmethod
    def from_config(config: dict) -> "LLMClient":
        """按配置构造。``provider`` 取 ``openai`` 或 ``deepseek``。"""
        provider_name = (config.get("provider") or "openai").lower()
        retry = RetryPolicy(**(config.get("retry") or {}))

        temperature = float(config.get("temperature", 0.7))
        model = config.get("model")

        provider: LLMProvider
        if provider_name == "deepseek":
            api_key = config.get("api_key") or os.getenv("DEEPSEEK_API_KEY", "")
            provider = DeepSeekProvider(
                api_key=api_key,
                model=model or "deepseek-chat",
                base_url=config.get("base_url") or "https://api.deepseek.com",
                temperature=temperature,
                max_tokens=int(config.get("max_tokens", 4000)),
            )
        elif provider_name == "openai":
            api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY", "")
            provider = OpenAIProvider(
                api_key=api_key,
                model=model or "gpt-4o-mini",
                base_url=config.get("base_url") or os.getenv("OPENAI_BASE_URL"),
                temperature=temperature,
                max_tokens=int(config.get("max_tokens", 2000)),
            )
        else:
            raise LLMAPIError(
                message=f"未知的 LLM provider: {provider_name}",
                code=CODE_LLM_ERROR,
                provider=provider_name,
                retryable=False,
                suggestions=["provider 只支持 openai 或 deepseek"],
            )

        return LLMClient(provider=provider, retry_policy=retry)
