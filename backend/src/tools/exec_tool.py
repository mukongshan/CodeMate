"""命令执行工具。

后端统一把 LLM 给出的 Linux shell 命令送进 WSL 执行。LLM 不需要、也不应该
在命令前加 ``wsl.exe``；这里负责 Windows 路径到 ``/mnt/<drive>`` 路径的转换、
固定工作目录、超时终止和输出捕获。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
from pathlib import Path, PureWindowsPath

from .base import Tool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300
# 单个流的输出上限。命令输出会进 LLM 上下文，不设限的话一个 npm install
# 就能把窗口撑爆。
MAX_OUTPUT_CHARS = 20_000


def run_command(
    command: str, workspace: str | Path, timeout: int = DEFAULT_TIMEOUT
) -> dict:
    """在 WSL bash 中执行一段 shell 命令，工作目录固定到 workspace。"""
    try:
        host_workspace = _ensure_workspace(workspace)
        wsl_workspace = _workspace_to_wsl_path(host_workspace)
        shell_command = f"cd {shlex.quote(wsl_workspace)} && {command}"
        popen_args = ["wsl.exe", "bash", "-lc", shell_command]

        result = subprocess.run(
            popen_args,
            timeout=timeout,
            shell=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
        return {
            "stdout": _decode_output(result.stdout),
            "stderr": _decode_wsl_stderr(result.stderr),
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
            "stderr": "找不到 wsl.exe，请确认 WSL 已安装并在 PATH 中",
            "exit_code": 127,
            "timed_out": False,
        }
    except OSError as exc:
        return {
            "stdout": "",
            "stderr": f"启动 WSL 进程失败: {exc}",
            "exit_code": 1,
            "timed_out": False,
        }


def _ensure_workspace(workspace: str | Path) -> Path:
    resolved = Path(workspace).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _workspace_to_wsl_path(workspace: str | Path) -> str:
    """把 Windows 工作区路径转换成 WSL 中的 /mnt 路径。"""
    resolved = Path(workspace).expanduser().resolve()
    if os.name != "nt":
        return str(resolved)

    win_path = PureWindowsPath(resolved)
    drive = win_path.drive.rstrip(":").lower()
    if not drive:
        raise OSError(f"WSL 工作区必须是带盘符的 Windows 路径: {resolved}")

    tail = "/".join(win_path.parts[1:])
    return f"/mnt/{drive}/{tail}" if tail else f"/mnt/{drive}"


def _decode_output(data: bytes | None) -> str:
    if not data:
        return ""
    if b"\x00" in data[:80]:
        return data.decode("utf-16le", errors="replace")
    return data.decode("utf-8", errors="replace")


def _decode_wsl_stderr(data: bytes | None) -> str:
    if not data:
        return ""

    rest = data
    hidden: list[str] = []
    marker = b"\r\x00\n\x00"
    while rest.startswith(b"w\x00s\x00l\x00:\x00"):
        end = rest.find(marker)
        if end < 0:
            break
        raw_line = rest[: end + len(marker)]
        decoded_line = raw_line.decode("utf-16le", errors="replace").strip()
        rest = rest[end + len(marker) :]
        if _is_wsl_startup_warning(decoded_line):
            continue
        hidden.append(decoded_line)

    parts = [part for part in hidden if part]
    decoded_rest = _decode_output(rest).strip()
    if decoded_rest:
        parts.append(decoded_rest)
    return "\n".join(parts)


def _is_wsl_startup_warning(line: str) -> bool:
    return line.startswith("wsl:") and "localhost" in line and "WSL" in line


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n...（输出过长，已截断，原长度 {len(text)} 字符）", True


def _diagnose(stderr: str, command: str) -> list[str]:
    """按常见错误给出修正建议。"""
    lower = stderr.lower()
    suggestions: list[str] = []
    if "not found" in lower or "not recognized" in lower:
        suggestions.append("命令不存在，确认工具已安装且在 WSL 的 PATH 中")
        suggestions.append("可以先用 ls、grep 或 read_file 确认项目用的是哪个工具链")
    if "permission denied" in lower or "access is denied" in lower:
        suggestions.append("权限不足，检查文件权限或换一个不需要提权的做法")
    if "no such file" in lower or "cannot find the path" in lower:
        suggestions.append("路径不存在，确认它是 WSL 中可访问的 Linux 路径")
    if not suggestions:
        suggestions.append(f"检查命令的参数是否正确: {command}")
    return suggestions


class BashTool(Tool):
    name = "bash"
    description = (
        "在 WSL 的 Linux bash shell 中执行命令并返回输出。"
        "直接传 Linux 命令，不要添加 wsl.exe 前缀。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "要执行的 Linux shell 命令。示例: python3 -m pytest tests/。"
                    "不要添加 wsl.exe 前缀。"
                ),
            },
            "timeout": {
                "type": "integer",
                "description": f"超时秒数，默认 {DEFAULT_TIMEOUT}，上限 {MAX_TIMEOUT}",
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = _ensure_workspace(workspace)

    async def execute(  # type: ignore[override]
        self, command: str, timeout: int = DEFAULT_TIMEOUT
    ) -> ToolResult:
        if not command or not command.strip():
            return ToolResult.error("command 不能为空")

        timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        result = await asyncio.to_thread(
            run_command, command.strip(), self.workspace, timeout
        )
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
