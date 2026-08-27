"""
文件操作工具

提供文件读写、列表等功能
"""

import os
from pathlib import Path
from typing import Dict, Any

from .base import Tool
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ReadFileTool(Tool):
    """读取文件工具"""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取指定文件的内容"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要读取的文件路径（相对于工作空间）"
                }
            },
            "required": ["file_path"]
        }

    def execute(self, file_path: str) -> str:
        """读取文件"""
        try:
            full_path = self.workspace / file_path
            logger.info(f"读取文件: {full_path}")

            if not full_path.exists():
                return f"错误：文件不存在: {file_path}"

            if not full_path.is_file():
                return f"错误：不是文件: {file_path}"

            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return f"文件内容 ({file_path}):\n{content}"

        except Exception as e:
            logger.error(f"读取文件失败: {e}")
            return f"读取文件失败: {str(e)}"


class WriteFileTool(Tool):
    """写入文件工具"""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "将内容写入到指定文件，如果文件不存在则创建，存在则覆盖"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要写入的文件路径（相对于工作空间）"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容"
                }
            },
            "required": ["file_path", "content"]
        }

    def execute(self, file_path: str, content: str) -> str:
        """写入文件"""
        try:
            full_path = self.workspace / file_path
            logger.info(f"写入文件: {full_path}")

            # 创建目录
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return f"成功写入文件: {file_path}"

        except Exception as e:
            logger.error(f"写入文件失败: {e}")
            return f"写入文件失败: {str(e)}"


class ListFilesTool(Tool):
    """列出文件工具"""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return "列出指定目录下的文件和子目录"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "要列出的目录路径（相对于工作空间），默认为根目录",
                    "default": "."
                }
            }
        }

    def execute(self, directory: str = ".") -> str:
        """列出文件"""
        try:
            full_path = self.workspace / directory
            logger.info(f"列出目录: {full_path}")

            if not full_path.exists():
                return f"错误：目录不存在: {directory}"

            if not full_path.is_dir():
                return f"错误：不是目录: {directory}"

            items = []
            for item in sorted(full_path.iterdir()):
                rel_path = item.relative_to(self.workspace)
                if item.is_dir():
                    items.append(f"[目录] {rel_path}/")
                else:
                    size = item.stat().st_size
                    items.append(f"[文件] {rel_path} ({size} bytes)")

            if not items:
                return f"目录为空: {directory}"

            return f"目录内容 ({directory}):\n" + "\n".join(items)

        except Exception as e:
            logger.error(f"列出文件失败: {e}")
            return f"列出文件失败: {str(e)}"
