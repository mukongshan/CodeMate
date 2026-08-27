"""
工具注册表

管理所有可用的工具：
1. 工具注册
2. 工具查询
3. 工具执行
"""

from pathlib import Path
from typing import Dict, Any, List

from .base import Tool
from .file_tools import ReadFileTool, WriteFileTool, ListFilesTool
from .exec_tool import ExecuteCommandTool
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册表"""

    def __init__(self, workspace: Path):
        """
        初始化工具注册表

        Args:
            workspace: 工作空间路径
        """
        self.workspace = workspace
        self.tools: Dict[str, Tool] = {}

        # 注册默认工具
        self._register_default_tools()

        logger.info(f"工具注册表初始化完成，已注册 {len(self.tools)} 个工具")

    def _register_default_tools(self):
        """注册默认工具"""
        default_tools = [
            ReadFileTool(self.workspace),
            WriteFileTool(self.workspace),
            ListFilesTool(self.workspace),
            ExecuteCommandTool(self.workspace),
        ]

        for tool in default_tools:
            self.register(tool)

    def register(self, tool: Tool):
        """
        注册工具

        Args:
            tool: 工具实例
        """
        self.tools[tool.name] = tool
        logger.debug(f"注册工具: {tool.name}")

    def get_tool(self, name: str) -> Tool:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例

        Raises:
            KeyError: 工具不存在
        """
        if name not in self.tools:
            raise KeyError(f"工具不存在: {name}")
        return self.tools[name]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        获取所有工具的 schema

        Returns:
            工具 schema 列表
        """
        return [tool.get_schema() for tool in self.tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        执行工具

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            执行结果

        Raises:
            KeyError: 工具不存在
            Exception: 工具执行失败
        """
        tool = self.get_tool(name)
        logger.info(f"执行工具: {name}")

        try:
            result = tool.execute(**arguments)
            return result
        except Exception as e:
            error_msg = f"工具执行失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise
