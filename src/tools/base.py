"""
工具基类

所有工具都继承自这个基类
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class Tool(ABC):
    """工具基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        工具参数 schema（JSON Schema 格式）

        返回格式：
        {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "参数1描述"},
                "param2": {"type": "number", "description": "参数2描述"}
            },
            "required": ["param1"]
        }
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """
        执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            执行结果（字符串形式）
        """
        pass

    def get_schema(self) -> Dict[str, Any]:
        """
        获取工具的 OpenAI function calling schema

        Returns:
            工具 schema
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
