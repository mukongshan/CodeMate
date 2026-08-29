"""搜索工具：glob / grep。

对应功能设计 05-工具系统 3.5/3.6 节。

这两个工具是"不做 RAG / 向量检索"这个决策的直接后果（14 号文档 5.1 节）：
实时 grep + glob 就是本项目的代码检索方案，所以它们的输出质量直接决定
Agent 能不能找到相关代码。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Iterator, Optional

from ..permission.rules import is_safe_path, resolve_in_workspace
from .base import Tool, ToolResult

# 搜索时跳过的目录（05 号文档 3.5 节列了前三个，其余是同类补充）
IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "target",
        "coverage",
        ".tox",
    }
)

DEFAULT_GLOB_LIMIT = 100
DEFAULT_GREP_CONTEXT = 2
MAX_GREP_MATCHES = 80
# grep 时跳过的大文件，避免在生成物上浪费时间
GREP_MAX_FILE_SIZE = 512 * 1024


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part in IGNORE_DIRS for part in parts)


class GlobTool(Tool):
    name = "glob"
    description = (
        "按 glob 模式查找文件，返回按修改时间倒序排列的路径列表。"
        "自动跳过 .git、node_modules、__pycache__ 等目录。"
        "支持 * ? [abc] 和跨目录的 **。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "glob 模式。示例: **/*.py、src/**/*.test.js",
            },
            "limit": {
                "type": "integer",
                "description": f"最多返回多少个结果，默认 {DEFAULT_GLOB_LIMIT}",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    async def execute(  # type: ignore[override]
        self, pattern: str, limit: int = DEFAULT_GLOB_LIMIT
    ) -> ToolResult:
        if not pattern or not pattern.strip():
            return ToolResult.error(
                "pattern 不能为空", suggestions=["示例: **/*.py"]
            )
        if limit <= 0:
            limit = DEFAULT_GLOB_LIMIT
        return await asyncio.to_thread(self._glob, pattern, limit)

    def _glob(self, pattern: str, limit: int) -> ToolResult:
        # 绝对路径模式会绕过 workspace 约束，直接拒绝
        if Path(pattern).is_absolute():
            return ToolResult.error(
                "pattern 必须是相对于工作目录的模式，不能用绝对路径",
                suggestions=["改成 **/*.py 这样的相对模式"],
            )

        try:
            matched = [
                p
                for p in self.workspace.glob(pattern)
                if p.is_file() and not _is_ignored(p, self.workspace)
            ]
        except (ValueError, NotImplementedError) as exc:
            return ToolResult.error(
                f"glob 模式非法: {exc}",
                suggestions=["检查模式语法，示例: **/*.py"],
            )

        # 越界过滤：pattern 里可能有 ../
        matched = [p for p in matched if is_safe_path(str(p), self.workspace)]
        matched.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        total = len(matched)
        truncated = total > limit
        shown = matched[:limit]

        if not shown:
            return ToolResult.ok(
                f"没有匹配 {pattern} 的文件",
                pattern=pattern,
                total=0,
                truncated=False,
            )

        lines = [str(p.relative_to(self.workspace)).replace("\\", "/") for p in shown]
        header = f"找到 {total} 个文件"
        if truncated:
            header += f"（只显示前 {limit} 个，按修改时间倒序）"
        body = "\n".join(lines)

        return ToolResult.ok(
            f"{header}:\n{body}",
            pattern=pattern,
            total=total,
            truncated=truncated,
        )


class GrepTool(Tool):
    name = "grep"
    description = (
        "在文件或目录中按正则搜索，返回匹配行及其上下文。"
        "目录搜索会递归并跳过 .git、node_modules 等目录和二进制文件。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {
                "type": "string",
                "description": "搜索的文件或目录（相对于工作目录），默认整个工作目录",
            },
            "context": {
                "type": "integer",
                "description": f"每个匹配前后各显示多少行上下文，默认 {DEFAULT_GREP_CONTEXT}",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "是否忽略大小写，默认 false",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    async def execute(  # type: ignore[override]
        self,
        pattern: str,
        path: str = ".",
        context: int = DEFAULT_GREP_CONTEXT,
        ignore_case: bool = False,
    ) -> ToolResult:
        if not pattern:
            return ToolResult.error("pattern 不能为空")
        if not is_safe_path(path, self.workspace):
            return ToolResult.error(
                f"路径超出工作目录范围: {path}",
                suggestions=[f"只能搜索工作目录内: {self.workspace}"],
            )

        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return ToolResult.error(
                f"正则表达式非法: {exc}",
                suggestions=["检查括号、方括号是否配对", "特殊字符需要用 \\ 转义"],
            )

        context = max(0, min(context, 10))
        target = resolve_in_workspace(path, self.workspace)
        return await asyncio.to_thread(self._grep, regex, target, context, pattern)

    def _grep(
        self, regex: re.Pattern[str], target: Path, context: int, raw_pattern: str
    ) -> ToolResult:
        if not target.exists():
            return ToolResult.error(
                f"路径不存在: {self._rel(target)}",
                suggestions=["用 glob 工具确认路径是否正确"],
            )

        files = [target] if target.is_file() else list(self._walk(target))
        blocks: list[str] = []
        per_file_counts: dict[str, int] = {}
        total_matches = 0
        truncated = False

        for file_path in files:
            hits = self._search_file(regex, file_path, context)
            if not hits:
                continue
            rel = self._rel(file_path)
            per_file_counts[rel] = len(hits)
            total_matches += len(hits)
            for line_no, snippet in hits:
                if len(blocks) >= MAX_GREP_MATCHES:
                    truncated = True
                    break
                blocks.append(f"{rel}:{line_no}\n{snippet}")
            if truncated:
                break

        if total_matches == 0:
            return ToolResult.ok(
                f"没有找到匹配 {raw_pattern} 的内容",
                pattern=raw_pattern,
                total=0,
                files_searched=len(files),
            )

        header = f"在 {len(per_file_counts)} 个文件中找到 {total_matches} 处匹配"
        parts = [header, ""]
        if truncated:
            # 结果过多时给出文件分布统计，帮模型判断该往哪个文件里细看
            distribution = ", ".join(
                f"{name} ({count})"
                for name, count in sorted(
                    per_file_counts.items(), key=lambda kv: kv[1], reverse=True
                )[:10]
            )
            parts.append(
                f"（结果过多，只显示前 {MAX_GREP_MATCHES} 处。分布: {distribution}）"
            )
            parts.append("")
        parts.append("\n---\n".join(blocks))

        return ToolResult.ok(
            "\n".join(parts),
            pattern=raw_pattern,
            total=total_matches,
            truncated=truncated,
            files_matched=len(per_file_counts),
        )

    def _walk(self, root: Path) -> Iterator[Path]:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if _is_ignored(path, self.workspace):
                continue
            try:
                if path.stat().st_size > GREP_MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            yield path

    @staticmethod
    def _search_file(
        regex: re.Pattern[str], path: Path, context: int
    ) -> list[tuple[int, str]]:
        try:
            raw = path.read_bytes()
        except OSError:
            return []
        if b"\x00" in raw[:8192]:
            return []
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gbk")
            except UnicodeDecodeError:
                return []

        lines = text.splitlines()
        hits: list[tuple[int, str]] = []
        for i, line in enumerate(lines):
            if not regex.search(line):
                continue
            start = max(0, i - context)
            end = min(len(lines), i + context + 1)
            snippet_lines = []
            for j in range(start, end):
                marker = ">" if j == i else " "
                snippet_lines.append(f"{marker} {j + 1}\t{lines[j]}")
            hits.append((i + 1, "\n".join(snippet_lines)))
        return hits

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.workspace)).replace("\\", "/")
        except ValueError:
            return str(path)
