"""受工作区限制的交互式终端进程。"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    tail = "/".join(resolved.parts[1:])
    return f"/mnt/{drive}/{tail}" if tail else f"/mnt/{drive}"


def _command(workspace: Path) -> tuple[list[str], Path | None]:
    if os.name == "nt" and shutil.which("wsl.exe"):
        return ["wsl.exe", "--cd", _wsl_path(workspace), "bash", "--noprofile", "--norc", "-i"], None
    if os.name == "nt":
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", "-"], workspace
    shell = os.environ.get("SHELL") or "/bin/bash"
    return [shell, "-i"], workspace


class TerminalSession:
    def __init__(self, terminal_id: str, process: asyncio.subprocess.Process, lane: str) -> None:
        self.terminal_id = terminal_id
        self.process = process
        self.lane = lane
        self.output_task: asyncio.Task[None] | None = None

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    async def write(self, text: str) -> None:
        if not self.alive or self.process.stdin is None:
            return
        self.process.stdin.write(text.encode("utf-8"))
        await self.process.stdin.drain()

    async def signal(self, name: str) -> None:
        if not self.alive:
            return
        if name in {"kill", "terminate"}:
            self.process.terminate()
        else:
            self.process.terminate()

    async def close(self) -> None:
        if self.output_task is not None and self.output_task is not asyncio.current_task() and not self.output_task.done():
            self.output_task.cancel()
            await asyncio.gather(self.output_task, return_exceptions=True)
        if self.alive:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()


async def open_terminal(workspace: Path | str, lane: str) -> TerminalSession:
    command, cwd = _command(Path(workspace))
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd) if cwd else None,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    return TerminalSession(f"term_{uuid.uuid4().hex[:12]}", process, lane)


async def read_output(session: TerminalSession, emit) -> None:
    stream = session.process.stdout
    if stream is None:
        return
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        await emit(
            "terminal_output",
            {"terminal_id": session.terminal_id, "lane": session.lane, "text": chunk.decode("utf-8", errors="replace")},
        )
    returncode = await session.process.wait()
    await emit(
        "terminal_exit",
        {"terminal_id": session.terminal_id, "lane": session.lane, "exit_code": returncode},
    )
