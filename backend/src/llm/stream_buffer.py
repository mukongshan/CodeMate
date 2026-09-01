"""流式响应的工具调用累积器。

对应功能设计 06-LLM接口层 7.1 节。

**为什么必须有这个东西**：OpenAI 流式响应把工具调用的 ``arguments`` 拆成很多个
chunk 逐段下发，``name`` 和 ``id`` 只在第一个 chunk 出现，后续 chunk 只带
``index`` 和一段参数片段。所以不能在单个 chunk 里 ``json.loads(arguments)``——
那样几乎每次多 chunk 的工具调用都会抛 JSONDecodeError。

必须按 ``index`` 累积（不是按 id，因为后续 chunk 的 id 是 None），
等整段拼完再一次性解析。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _PartialToolCall:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class StreamBuffer:
    """累积流式响应中的文本与工具调用片段。"""

    text: str = ""
    _partials: dict[int, _PartialToolCall] = field(default_factory=dict)

    def add_text_delta(self, text: str) -> None:
        self.text += text

    def add_tool_call_delta(
        self, index: int, call_id: str | None, name: str | None, arguments: str | None
    ) -> None:
        """累积一个工具调用片段。

        按 ``index`` 建槽，``id``/``name`` 只在首个片段出现时记录，
        ``arguments`` 逐段拼接。
        """
        partial = self._partials.get(index)
        if partial is None:
            partial = _PartialToolCall(index=index)
            self._partials[index] = partial

        if call_id:
            partial.id = call_id
        if name:
            partial.name += name
        if arguments:
            partial.arguments += arguments

    def has_tool_calls(self) -> bool:
        return bool(self._partials)

    def get_complete_tool_calls(self) -> list[dict]:
        """取出参数已完整的工具调用，按 index 顺序返回。

        参数解析失败的调用会被丢弃并记日志——把半截 JSON 传给工具执行层
        只会在更深的地方炸，不如在这里拦住。
        """
        result: list[dict] = []
        for index in sorted(self._partials):
            partial = self._partials[index]
            if not partial.name:
                logger.warning("工具调用片段 index=%d 缺少 name，丢弃", index)
                continue

            raw_args = partial.arguments.strip()
            # 无参工具的 arguments 可能是空串或 "{}"，两者都当成无参
            if not raw_args:
                result.append({"id": partial.id, "name": partial.name, "arguments": {}})
                continue

            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "工具调用 %s 的参数 JSON 不完整，丢弃该调用: %s", partial.name, exc
                )
                continue

            if not isinstance(parsed, dict):
                logger.warning(
                    "工具调用 %s 的参数不是对象（实际 %s），丢弃",
                    partial.name,
                    type(parsed).__name__,
                )
                continue

            result.append(
                {"id": partial.id, "name": partial.name, "arguments": parsed}
            )
        return result

    def has_incomplete_tool_calls(self) -> bool:
        """判断是否存在无法安全执行的工具调用片段。"""
        for partial in self._partials.values():
            if not partial.name:
                return True

            raw_args = partial.arguments.strip()
            if not raw_args:
                continue

            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                return True
            if not isinstance(parsed, dict):
                return True
        return False

    def clear(self) -> None:
        self.text = ""
        self._partials.clear()
