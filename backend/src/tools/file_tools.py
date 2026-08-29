"""文件读写工具：read_file / write_file / edit_file。

对应功能设计 05-工具系统 3.1/3.2/3.3 节。

三个工具共享一套路径解析与边界检查——路径安全是 workspace 约束的第一道防线
（10 号文档一节：路径穿越靠输入校验兜住，不靠隔离）。
"""

from __future__ import annotations

import asyncio
import difflib
import logging
from pathlib import Path
from typing import Optional

from ..permission.rules import is_safe_path, resolve_in_workspace
from .base import Tool, ToolResult

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 1024 * 1024  # 1MB（05 号文档 3.1 节）
# 超过这个行数就只返回头尾，中间用省略标记。避免一个几万行的文件
# 直接吃掉整个上下文窗口。
MAX_LINES_INLINE = 800
_ENCODING_CANDIDATES = ("utf-8", "utf-8-sig", "gbk", "latin-1")


class _WorkspaceTool(Tool):
    """带 workspace 约束的工具基类。"""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    def _resolve(self, path: str) -> tuple[Optional[Path], Optional[ToolResult]]:
        """解析路径并做边界检查。越界时返回错误结果。"""
        if not path or not path.strip():
            return None, ToolResult.error(
                "路径不能为空", suggestions=["提供相对于工作目录的文件路径"]
            )
        if not is_safe_path(path, self.workspace):
            return None, ToolResult.error(
                f"路径超出工作目录范围: {path}",
                suggestions=[
                    f"只能访问工作目录内的文件: {self.workspace}",
                    "使用相对路径，如 src/main.py",
                ],
            )
        return resolve_in_workspace(path, self.workspace), None

    def _rel(self, path: Path) -> str:
        """转成相对 workspace 的显示路径，日志和提示里更短。"""
        try:
            return str(path.relative_to(self.workspace))
        except ValueError:
            return str(path)


def _decode(raw: bytes) -> tuple[Optional[str], Optional[str]]:
    """按候选编码依次尝试解码，返回 ``(文本, 编码名)``。

    不引入 chardet：候选表覆盖了实际会遇到的情况（UTF-8、带 BOM 的 UTF-8、
    中文 Windows 的 GBK），latin-1 作为兜底永不失败。
    """
    for encoding in _ENCODING_CANDIDATES:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def _looks_binary(raw: bytes) -> bool:
    """NUL 字节是二进制文件最可靠的信号。"""
    return b"\x00" in raw[:8192]


class ReadFileTool(_WorkspaceTool):
    name = "read_file"
    description = (
        "读取指定路径的文件，返回带行号的文本内容。"
        "自动检测编码，二进制文件会返回提示而不是乱码。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（相对于工作目录）。示例: src/main.py",
            }
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> ToolResult:  # type: ignore[override]
        target, err = self._resolve(path)
        if err is not None:
            return err
        assert target is not None
        return await asyncio.to_thread(self._read, target, path)

    def _read(self, target: Path, original: str) -> ToolResult:
        if not target.exists():
            return ToolResult.error(
                f"文件不存在: {original}",
                suggestions=[
                    "检查路径拼写是否正确",
                    "使用 glob 工具查找文件: glob(pattern='**/*.py')",
                    f"使用 bash 工具列出目录: bash(command='ls {Path(original).parent}')",
                ],
            )
        if target.is_dir():
            return ToolResult.error(
                f"这是一个目录，不是文件: {original}",
                suggestions=["用 glob 工具列出目录内容"],
            )

        size = target.stat().st_size
        if size > MAX_FILE_SIZE:
            return ToolResult.error(
                f"文件过大: {size} 字节（上限 {MAX_FILE_SIZE} 字节）",
                suggestions=[
                    "用 grep 工具搜索文件中的关键内容",
                    "用 bash 工具配合 head/tail 读取片段",
                ],
            )

        try:
            raw = target.read_bytes()
        except OSError as exc:
            return ToolResult.error(f"读取失败: {exc}")

        if _looks_binary(raw):
            return ToolResult.error(
                f"这是一个二进制文件（{size} 字节），无法作为文本读取: {original}",
                suggestions=["如需查看，用 bash 工具配合专门的命令"],
            )

        text, encoding = _decode(raw)
        if text is None:
            return ToolResult.error(
                f"无法解码文件内容: {original}",
                suggestions=[f"已尝试的编码: {', '.join(_ENCODING_CANDIDATES)}"],
            )

        lines = text.splitlines()
        # 加行号：edit_file 的匹配失败提示会报告行号，读的时候带上行号
        # 模型才能准确定位（而且能直接引用行号跟用户讨论）
        if len(lines) > MAX_LINES_INLINE:
            head = lines[: MAX_LINES_INLINE // 2]
            tail = lines[-(MAX_LINES_INLINE // 2) :]
            numbered = _number_lines(head, 1)
            numbered += f"\n… 省略 {len(lines) - len(head) - len(tail)} 行 …\n"
            numbered += _number_lines(tail, len(lines) - len(tail) + 1)
            truncated = True
        else:
            numbered = _number_lines(lines, 1)
            truncated = False

        return ToolResult.ok(
            numbered,
            path=self._rel(target),
            lines=len(lines),
            size=size,
            encoding=encoding,
            truncated=truncated,
        )


def _number_lines(lines: list[str], start: int) -> str:
    width = len(str(start + len(lines) - 1))
    return "\n".join(
        f"{str(i).rjust(width)}\t{line}" for i, line in enumerate(lines, start)
    )


class WriteFileTool(_WorkspaceTool):
    name = "write_file"
    description = (
        "把内容写入指定文件，覆盖原有内容。父目录不存在时会自动创建。"
        "已存在的文件会先备份为 .bak。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（相对于工作目录）。示例: src/utils.py",
            },
            "content": {"type": "string", "description": "要写入的完整文本内容"},
            "create_dirs": {
                "type": "boolean",
                "description": "父目录不存在时是否自动创建，默认 true",
            },
        },
        "required": ["path", "content"],
    }

    async def execute(  # type: ignore[override]
        self, path: str, content: str, create_dirs: bool = True
    ) -> ToolResult:
        target, err = self._resolve(path)
        if err is not None:
            return err
        assert target is not None
        return await asyncio.to_thread(self._write, target, content, create_dirs)

    def _write(self, target: Path, content: str, create_dirs: bool) -> ToolResult:
        existed = target.exists()
        if existed and target.is_dir():
            return ToolResult.error(f"目标是一个目录，无法写入: {self._rel(target)}")

        if not target.parent.exists():
            if not create_dirs:
                return ToolResult.error(
                    f"父目录不存在: {self._rel(target.parent)}",
                    suggestions=["传 create_dirs=true 让工具自动创建"],
                )
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return ToolResult.error(f"创建目录失败: {exc}")

        backup: Optional[Path] = None
        if existed:
            backup = target.with_suffix(target.suffix + ".bak")
            try:
                backup.write_bytes(target.read_bytes())
            except OSError as exc:
                logger.warning("备份 %s 失败: %s", target, exc)
                backup = None

        try:
            target.write_text(content, encoding="utf-8", newline="\n")
        except OSError as exc:
            # 写失败时把备份还原回去，保证不留下半截文件
            if backup is not None and backup.exists():
                try:
                    target.write_bytes(backup.read_bytes())
                except OSError:
                    pass
            return ToolResult.error(f"写入失败: {exc}")

        line_count = content.count("\n") + (1 if content else 0)
        verb = "覆盖" if existed else "创建"
        return ToolResult.ok(
            f"已{verb}文件 {self._rel(target)}（{line_count} 行，{len(content)} 字符）"
            + (f"，原文件备份为 {backup.name}" if backup else ""),
            path=self._rel(target),
            created=not existed,
            lines=line_count,
        )


class EditFileTool(_WorkspaceTool):
    name = "edit_file"
    description = (
        "把文件中的一段文本替换成新文本。old_string 必须在文件中唯一出现；"
        "找不到或找到多处时会返回提示而不做修改。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于工作目录）"},
            "old_string": {
                "type": "string",
                "description": "要被替换的原文本，必须在文件中唯一出现",
            },
            "new_string": {"type": "string", "description": "替换后的新文本"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def execute(  # type: ignore[override]
        self, path: str, old_string: str, new_string: str
    ) -> ToolResult:
        target, err = self._resolve(path)
        if err is not None:
            return err
        assert target is not None
        return await asyncio.to_thread(self._edit, target, old_string, new_string)

    def _edit(self, target: Path, old: str, new: str) -> ToolResult:
        if not target.exists():
            return ToolResult.error(
                f"文件不存在: {self._rel(target)}",
                suggestions=["先用 read_file 确认文件路径", "或用 write_file 创建新文件"],
            )
        if old == new:
            return ToolResult.error(
                "old_string 与 new_string 相同，无需修改",
                suggestions=["确认要修改的内容是否正确"],
            )

        try:
            raw = target.read_bytes()
        except OSError as exc:
            return ToolResult.error(f"读取失败: {exc}")

        text, encoding = _decode(raw)
        if text is None:
            return ToolResult.error(f"无法解码文件内容: {self._rel(target)}")

        count = text.count(old)
        if count == 0:
            return self._no_match_result(target, text, old)
        if count > 1:
            locations = _match_line_numbers(text, old)
            return ToolResult.error(
                f"old_string 在文件中出现了 {count} 次，无法确定要改哪一处",
                suggestions=[
                    f"匹配位置在第 {', '.join(str(n) for n in locations)} 行",
                    "在 old_string 里多带几行上下文，让它唯一",
                ],
            )

        updated = text.replace(old, new, 1)
        backup = target.with_suffix(target.suffix + ".bak")
        try:
            backup.write_bytes(raw)
        except OSError as exc:
            logger.warning("备份 %s 失败: %s", target, exc)

        try:
            target.write_text(updated, encoding=encoding or "utf-8", newline="")
        except OSError as exc:
            return ToolResult.error(f"写入失败: {exc}")

        diff = _make_diff(text, updated, self._rel(target))
        changed = abs(updated.count("\n") - text.count("\n")) or 1
        return ToolResult.ok(
            f"已修改 {self._rel(target)}\n\n{diff}",
            path=self._rel(target),
            changes=changed,
        )

    def _no_match_result(self, target: Path, text: str, old: str) -> ToolResult:
        """找不到匹配时给出最相似的内容和行号（05 号文档 3.3 节）。"""
        best_block, best_line = _find_similar_block(text, old)
        suggestions = [
            "检查空白字符、缩进和参数名是否完全一致",
            "先用 read_file 读取当前内容，再基于实际文本构造 old_string",
        ]
        message = f"未在 {self._rel(target)} 中找到 old_string"
        if best_block:
            message += (
                f"\n\n你要查找的：\n{_indent(old)}\n\n"
                f"最相似的内容（第 {best_line} 行）：\n{_indent(best_block)}"
            )
            suggestions.insert(0, "上面列出了最相似的内容，注意两者的差异")
        return ToolResult.error(message, suggestions=suggestions)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _match_line_numbers(text: str, needle: str) -> list[int]:
    numbers: list[int] = []
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            break
        numbers.append(text.count("\n", 0, idx) + 1)
        start = idx + 1
    return numbers


def _find_similar_block(text: str, needle: str) -> tuple[Optional[str], int]:
    """滑动窗口找最相似的同行数文本块。

    用 difflib.SequenceMatcher 的相似度而不是自己实现 Levenshtein：
    标准库够用，而且它对"空白差异"这种最常见的失配原因足够敏感。
    """
    lines = text.splitlines()
    needle_lines = needle.splitlines()
    if not lines or not needle_lines:
        return None, 0

    window = len(needle_lines)
    normalized_needle = " ".join(needle.split())
    best_ratio = 0.0
    best_block: Optional[str] = None
    best_line = 0

    for i in range(max(1, len(lines) - window + 1)):
        block_lines = lines[i : i + window]
        block = "\n".join(block_lines)
        ratio = difflib.SequenceMatcher(
            None, normalized_needle, " ".join(block.split())
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_block = block
            best_line = i + 1

    # 相似度太低就不给建议了，免得贴一段毫不相关的代码反而误导
    if best_ratio < 0.5:
        return None, 0
    return best_block, best_line


def _make_diff(before: str, after: str, filename: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
            n=2,
        )
    )
    if len(diff_lines) > 60:
        diff_lines = diff_lines[:60] + ["… diff 过长已截断 …"]
    return "\n".join(diff_lines)
