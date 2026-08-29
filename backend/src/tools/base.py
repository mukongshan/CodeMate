"""工具基类与统一结果类型。

对应功能设计 05-工具系统 四、五节，代码设计 01 号文档四节。

``ToolResult`` 把成功和失败合并成一个类型（不引入 ``Result[T, E]`` 泛型，
理由见 01 号文档六节）：``content`` 是唯一喂给 LLM 的通道，``metadata``
只给前端和日志看，不进 LLM 上下文。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..permission.manager import PermissionLevel


@dataclass
class ToolResult:
    """一次工具执行的结果。"""

    content: str = ""
    is_error: bool = False
    metadata: dict = field(default_factory=dict)
    suggestions: Optional[list[str]] = None

    @property
    def success(self) -> bool:
        return not self.is_error

    def to_llm_text(self) -> str:
        """渲染成喂给 LLM 的文本，失败时把建议拼进去。

        建议必须进 LLM 上下文——这是让模型自我纠错的关键（08 号文档 6.1 节）：
        告诉它"文件不存在"不如同时告诉它"可以用 glob 找找"。
        """
        if not self.is_error:
            return self.content

        lines = [f"错误: {self.content}"]
        if self.suggestions:
            lines.append("")
            lines.append("建议:")
            for i, suggestion in enumerate(self.suggestions, 1):
                lines.append(f"  {i}. {suggestion}")
        return "\n".join(lines)

    @staticmethod
    def ok(content: str, **metadata: Any) -> "ToolResult":
        return ToolResult(content=content, metadata=dict(metadata))

    @staticmethod
    def error(
        message: str,
        suggestions: Optional[list[str]] = None,
        **metadata: Any,
    ) -> "ToolResult":
        return ToolResult(
            content=message,
            is_error=True,
            suggestions=suggestions,
            metadata=dict(metadata),
        )


class Tool(ABC):
    """工具基类。

    子类声明 ``name`` / ``description`` / ``parameters``（JSON Schema），
    实现 ``execute``。权限级别由 ``TOOL_PERMISSIONS`` 统一登记，
    工具自己不做权限检查。
    """

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @property
    def permission_level(self) -> PermissionLevel:
        from ..permission.manager import TOOL_PERMISSIONS

        return TOOL_PERMISSIONS.get(self.name, PermissionLevel.DANGEROUS)

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...

    def get_schema(self) -> dict:
        """转成 OpenAI function calling 的工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
