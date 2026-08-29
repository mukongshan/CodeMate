"""命令执行工具。

对应功能设计 05-工具系统 3.4 节、10-安全与沙箱 五节。

**没有 Docker 沙箱**（10 号文档 v0.2 已移除该方案，14 号文档 4.3 节确认）。
防线是两层：

1. 权限闸门——危险模式黑名单硬拒绝 + DANGEROUS 级别总是需要用户确认
2. 进程约束——固定 cwd、超时终止、``shell=False``、捕获输出

威胁模型是"LLM 判断失误或被读到的内容误导"，不是"防御恶意用户"。
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess
from pathlib import Path

from .base import Tool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300
# 单个流的输出上限。命令输出会进 LLM 上下文，不设限的话一个 npm install
# 就能把窗口撑爆。
MAX_OUTPUT_CHARS = 20_000

# shell 元字符：shell=False 下这些不会被解释，静默执行会得到意料之外的结果
# （比如 `echo a > f.txt` 会把 ">" 和 "f.txt" 当成 echo 的普通参数），
# 所以宁可明确报错并告诉模型该怎么改。
_SHELL_METACHARS = ("|", ">", "<", "&&", "||", ";", "`", "$(")


def run_command(
    command: list[str], workspace: str | Path, timeout: int = DEFAULT_TIMEOUT
) -> dict:
    """在进程级约束下执行命令。

    调用前必须已经过权限闸门（危险模式匹配 + 用户确认）。

    这个签名是刻意固定的：将来若要换成容器后端，替换这个函数的实现即可，
    不影响调用方（10 号文档六节）。
    """
    try:
        result = subprocess.run(
            command,
            cwd=str(workspace),
            timeout=timeout,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            # 阻断交互式命令：没有 stdin 的命令会立刻读到 EOF 而不是挂住等输入
            stdin=subprocess.DEVNULL,
        )
        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.returncode,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"命令超时（{timeout} 秒），已终止",
            "exit_code": -1,
            "timed_out": True,
        }
    except FileNotFoundError:
        return {
            "stdout": "",
            "stderr": f"找不到可执行文件: {command[0] if command else ''}",
            "exit_code": 127,
            "timed_out": False,
        }
    except OSError as exc:
        return {
            "stdout": "",
            "stderr": f"启动进程失败: {exc}",
            "exit_code": 1,
            "timed_out": False,
        }


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n…（输出过长，已截断，原长度 {len(text)} 字符）", True


def _diagnose(stderr: str, command: str) -> list[str]:
    """按常见错误给出修正建议（05 号文档 3.4 节）。"""
    lower = stderr.lower()
    suggestions: list[str] = []
    if "not found" in lower or "not recognized" in lower:
        suggestions.append("命令不存在，确认工具已安装且在 PATH 中")
        suggestions.append("可以先用 glob 或 read_file 确认项目用的是哪个工具链")
    if "permission denied" in lower or "access is denied" in lower:
        suggestions.append("权限不足，检查文件权限或换一个不需要提权的做法")
    if "no such file" in lower or "cannot find the path" in lower:
        suggestions.append("路径不存在，用 glob 工具确认实际路径")
    if not suggestions:
        suggestions.append(f"检查命令的参数是否正确: {command}")
    return suggestions


class BashTool(Tool):
    name = "bash"
    description = (
        "在工作目录中执行一条命令并返回输出。"
        "注意：不经过 shell，所以不支持管道 |、重定向 >、&& 等 shell 语法，"
        "一次只能执行一条命令。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的单条命令。示例: python -m pytest tests/",
            },
            "timeout": {
                "type": "integer",
                "description": f"超时秒数，默认 {DEFAULT_TIMEOUT}，上限 {MAX_TIMEOUT}",
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    async def execute(  # type: ignore[override]
        self, command: str, timeout: int = DEFAULT_TIMEOUT
    ) -> ToolResult:
        if not command or not command.strip():
            return ToolResult.error("command 不能为空")

        found = [m for m in _SHELL_METACHARS if m in command]
        if found:
            return ToolResult.error(
                f"命令包含 shell 语法 {' '.join(found)}，但本工具不经过 shell，这些符号不会生效",
                suggestions=[
                    "拆成多次 bash 调用，每次执行一条命令",
                    "需要写文件请用 write_file 工具，不要用重定向",
                    "需要过滤输出请用 grep 工具",
                ],
            )

        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            return ToolResult.error(
                f"命令解析失败（引号可能未闭合）: {exc}",
                suggestions=["检查命令中的引号是否配对"],
            )
        if not argv:
            return ToolResult.error("command 解析后为空")

        timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        result = await asyncio.to_thread(run_command, argv, self.workspace, timeout)
        return self._format(result, command)

    @staticmethod
    def _format(result: dict, command: str) -> ToolResult:
        stdout, out_truncated = _truncate(result["stdout"])
        stderr, err_truncated = _truncate(result["stderr"])
        exit_code = result["exit_code"]

        parts: list[str] = [f"$ {command}", f"exit_code: {exit_code}"]
        if stdout.strip():
            parts.append(f"\n[stdout]\n{stdout.rstrip()}")
        if stderr.strip():
            parts.append(f"\n[stderr]\n{stderr.rstrip()}")
        if not stdout.strip() and not stderr.strip():
            parts.append("\n（无输出）")
        body = "\n".join(parts)

        metadata = {
            "exit_code": exit_code,
            "timed_out": result["timed_out"],
            "truncated": out_truncated or err_truncated,
        }

        if result["timed_out"]:
            return ToolResult.error(
                body,
                suggestions=["命令耗时过长，考虑缩小任务范围或调大 timeout 参数"],
                **metadata,
            )
        if exit_code != 0:
            return ToolResult.error(
                body, suggestions=_diagnose(stderr, command), **metadata
            )
        return ToolResult.ok(body, **metadata)
