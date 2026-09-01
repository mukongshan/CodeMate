"""Workspace-scoped project instructions and lightweight memory loading."""

from __future__ import annotations

from pathlib import Path


_INSTRUCTION_NAMES = ("AGENTS.md", "CODEMATE.md")
_MEMORY_PATH = Path(".codemate") / "memory.md"
_MAX_FILE_BYTES = 128 * 1024
_MAX_CONTENT_CHARS = 12_000


def _read_text(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return ""
        content = path.read_text(encoding="utf-8")
        if len(content) > _MAX_CONTENT_CHARS:
            return content[:_MAX_CONTENT_CHARS] + "\n[文件内容已截断]"
        return content
    except (OSError, UnicodeError):
        return ""


def load_project_context(workspace: Path | str) -> str:
    """Load human-maintained instructions and memory inside one workspace."""
    root = Path(workspace).expanduser().resolve()
    sections: list[str] = []
    for name in _INSTRUCTION_NAMES:
        content = _read_text(root / name).strip()
        if content:
            sections.append(f"## 项目指令: {name}\n{content}")
    memory = _read_text(root / _MEMORY_PATH).strip()
    if memory:
        sections.append(f"## 工作区项目记忆: {_MEMORY_PATH.as_posix()}\n{memory}")
    if not sections:
        return ""
    return "\n\n".join(sections)
