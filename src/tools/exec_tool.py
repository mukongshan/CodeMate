"""
命令执行工具

在工作空间中执行 shell 命令
"""

import subprocess
from pathlib import Path
from typing import Dict, Any

from .base import Tool
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ExecuteCommandTool(Tool):
    """执行命令工具"""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    @property
    def name(self) -> str:
        return "execute_command"

    @property
    def description(self) -> str:
        return "在工作空间中执行 shell 命令，返回命令输出。注意：命令超时时间为 30 秒"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令"
                }
            },
            "required": ["command"]
        }

    def execute(self, command: str) -> str:
        """执行命令"""
        try:
            logger.info(f"执行命令: {command}")

            # 执行命令
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )

            # 构建输出
            output_lines = []

            if result.returncode == 0:
                output_lines.append(f"命令执行成功 (返回码: 0)")
            else:
                output_lines.append(f"命令执行失败 (返回码: {result.returncode})")

            if result.stdout:
                output_lines.append(f"\n标准输出:\n{result.stdout}")

            if result.stderr:
                output_lines.append(f"\n标准错误:\n{result.stderr}")

            return "\n".join(output_lines)

        except subprocess.TimeoutExpired:
            error_msg = f"命令执行超时（超过 30 秒）: {command}"
            logger.error(error_msg)
            return error_msg

        except Exception as e:
            error_msg = f"命令执行失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg
