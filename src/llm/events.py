"""LLM 接口层的数据类型：请求消息与流式事件。

对应功能设计 06-LLM接口层、代码设计 01 号文档三节。

``Message`` 是 **LLM API 协议格式**，和存储层的 ``Entry`` 是两套独立类型：
``Entry`` 要携带 parent/lane/seq 这些树结构信息，``Message`` 只关心协议字段。
转换在 ``TreeMessageProvider`` 内部完成（见 01 号文档八节）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """assistant 消息里的一次工具调用。"""

    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    """发给 LLM 的一条消息。

    ``content`` 允许为 None：assistant 只返回工具调用、没有文本时就是这种情况，
    OpenAI 协议要求此时 content 为 null 而不是空字符串。
    """

    role: MessageRole
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    tool_call_id: Optional[str] = None

    def to_api_dict(self) -> dict:
        """转成 OpenAI Chat Completions 协议的 message 对象。"""
        payload: dict = {"role": self.role}

        # role=tool 的消息必须带 tool_call_id，且 content 不能为 null
        if self.role == "tool":
            payload["content"] = self.content or ""
            payload["tool_call_id"] = self.tool_call_id
            return payload

        payload["content"] = self.content

        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        # 协议要求 arguments 是 JSON 字符串，不是对象
                        "arguments": _dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]
            # 有 tool_calls 且无文本时 content 必须显式为 None
            if not self.content:
                payload["content"] = None

        return payload


def _dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


# --- 流式事件 ---------------------------------------------------------------


@dataclass
class TextDeltaEvent:
    """文本增量。对应 WebSocket 的 text_delta 事件。"""

    text: str


@dataclass
class ToolCallEvent:
    """一次完整的工具调用请求（参数已跨 chunk 拼接完成）。"""

    id: str
    name: str
    arguments: dict


@dataclass
class DoneEvent:
    """本轮响应结束。

    ``stop_reason`` 取值遵循 OpenAI 的 finish_reason：``stop``（对应设计文档里的
    end_turn）、``tool_calls``、``length``（对应 max_tokens）。
    """

    stop_reason: str
    usage: dict = field(default_factory=dict)


@dataclass
class ErrorEvent:
    """流式过程中出错。"""

    message: str
    retryable: bool = False


LLMEvent = TextDeltaEvent | ToolCallEvent | DoneEvent | ErrorEvent

# 归一化 finish_reason：协议里的 "stop" 就是设计文档说的 end_turn
STOP_REASON_END_TURN = "stop"
STOP_REASON_TOOL_CALLS = "tool_calls"
STOP_REASON_LENGTH = "length"
