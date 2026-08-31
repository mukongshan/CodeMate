"""工具注册表与参数校验。

对应功能设计 05-工具系统 4.2 节，代码设计 03 号文档三节。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..errors.types import (
    CODE_TOOL_NOT_FOUND,
    CODE_VALIDATION_ERROR,
    ToolExecutionError,
    ValidationError,
)
from .base import Tool, ToolResult

logger = logging.getLogger(__name__)

# JSON Schema 类型 → Python 类型名。
# 'integer' 这一项容易漏：漏了会让所有带整型参数的工具（glob.limit、
# grep.context、bash.timeout）永远校验失败。
_TYPE_MAP: dict[str, tuple[str, ...]] = {
    "string": ("str",),
    "number": ("int", "float"),
    "integer": ("int",),
    "boolean": ("bool",),
    "array": ("list",),
    "object": ("dict",),
}


def validate_args(schema: dict, args: dict) -> list[str]:
    """按 JSON Schema 校验参数，返回错误列表（空表示通过）。"""
    errors: list[str] = []

    for field_name in schema.get("required", []):
        if field_name not in args:
            errors.append(f"缺少必需参数: {field_name}")

    properties = schema.get("properties", {})
    for key, value in args.items():
        if key not in properties:
            errors.append(f"未知参数: {key}")
            continue

        expected = properties[key].get("type")
        if expected is None:
            continue

        actual = type(value).__name__
        allowed = _TYPE_MAP.get(expected, ())
        # bool 是 int 的子类，但 type().__name__ 分得清，所以不必特殊处理
        if allowed and actual not in allowed:
            errors.append(f"参数 {key} 类型错误: 期望 {expected}，实际 {actual}")

    return errors


class ToolRegistry:
    """工具注册与调度。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("工具必须有 name")
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def tool_names(self) -> list[str]:
        return list(self._tools)

    def get_tool_schemas(self) -> list[dict]:
        return [t.get_schema() for t in self._tools.values()]

    async def execute(self, name: str, args: dict) -> ToolResult:
        """校验并执行。工具不存在或参数非法时抛异常，由 Agent 转成错误消息。"""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(
                message=f"工具不存在: {name}",
                code=CODE_TOOL_NOT_FOUND,
                tool_name=name,
                tool_args=args,
                suggestions=[f"可用工具: {', '.join(sorted(self._tools))}"],
            )

        errors = validate_args(tool.parameters, args)
        if errors:
            raise ValidationError(
                message=f"工具 {name} 的参数校验失败",
                code=CODE_VALIDATION_ERROR,
                tool_name=name,
                validation_errors=errors,
                suggestions=errors,
            )

        return await tool.execute(**args)

    # --- 预置组合 -----------------------------------------------------------

    @staticmethod
    def default(workspace: Path | str) -> "ToolRegistry":
        """注册主 Agent 的内置工具。

        子 Agent 工具由 Agent 层单独注册（避免循环导入）；联网工具只访问
        公共 HTTP(S) 资源，不获得工作区写权限。
        """
        from .exec_tool import BashTool
        from .file_tools import (
            EditFileTool,
            ListDirectoryTool,
            ReadFileTool,
            WriteFileTool,
        )
        from .search_tools import GlobTool, GrepTool
        from .web_tools import WebFetchTool, WebSearchTool

        ws = Path(workspace)
        registry = ToolRegistry()
        registry.register(ReadFileTool(ws))
        registry.register(WriteFileTool(ws))
        registry.register(EditFileTool(ws))
        registry.register(GlobTool(ws))
        registry.register(GrepTool(ws))
        registry.register(ListDirectoryTool(ws))
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())
        registry.register(BashTool(ws))
        return registry

    @staticmethod
    def readonly(workspace: Path | str) -> "ToolRegistry":
        """只读子集，供子 Agent 使用（15 号文档四节）。

        子 Agent 被定位成"侦察兵"而不是"执行者"：即使无人盯着它跑，
        风险也天然可控。
        """
        from .file_tools import ListDirectoryTool, ReadFileTool
        from .search_tools import GlobTool, GrepTool
        from .web_tools import WebFetchTool, WebSearchTool

        ws = Path(workspace)
        registry = ToolRegistry()
        registry.register(ReadFileTool(ws))
        registry.register(GlobTool(ws))
        registry.register(GrepTool(ws))
        registry.register(ListDirectoryTool(ws))
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())
        return registry
