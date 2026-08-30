"""权限判定的纯函数：路径安全、危险命令识别。

对应功能设计 09-权限控制系统 五、六节。

单独成文件（不和 PermissionManager 混在一起）是为了能独立做单元测试——
这些函数是安全边界，必须能穷举测试用例。
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Iterable


def resolve_in_workspace(path: str, workspace: str | Path) -> Path:
    """把用户给的路径解析为绝对路径。相对路径按 workspace 解释。"""
    ws = Path(workspace).expanduser().resolve()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = ws / p
    # 用 os.path.normpath 而不是 Path.resolve()：后者会跟随符号链接，
    # 但这里要判断的是"用户写的路径字面上是否越界"，且目标文件可能还不存在。
    return Path(os.path.normpath(str(p)))


def is_safe_path(path: str, workspace: str | Path) -> bool:
    """路径是否在 workspace 内（防目录穿越）。

    09 号文档 5.1 节给的是 ``abs_path.startswith(abs_workspace)``。这里换成
    ``Path.is_relative_to``，因为纯字符串前缀匹配在两种情况下会误判：

    - ``C:\\proj2`` 会被判成在 ``C:\\proj`` 内（前缀匹配但不是子目录）
    - Windows 路径大小写不敏感，``C:\\Proj`` 和 ``C:\\proj`` 是同一个目录

    ``normcase`` 在 Windows 上统一大小写和分隔符，在 POSIX 上是恒等变换。
    """
    ws = Path(workspace).expanduser().resolve()
    target = resolve_in_workspace(path, ws)

    norm_target = Path(os.path.normcase(str(target)))
    norm_ws = Path(os.path.normcase(str(ws)))
    return norm_target == norm_ws or norm_target.is_relative_to(norm_ws)


# 系统关键路径黑名单（09 号文档 5.2 节）。
# 补了 Windows 的对应目录——设计文档只列了 POSIX 路径，但本项目在 Windows 上跑，
# 只防 /etc/ 起不到实际作用。
SYSTEM_CRITICAL_PATHS: tuple[str, ...] = (
    # POSIX
    "/etc/",
    "/sys/",
    "/proc/",
    "/boot/",
    "/dev/",
    "/var/log/",
    "~/.ssh/",
    "~/.aws/",
    "~/.bashrc",
    "~/.bash_profile",
    "~/.zshrc",
    "~/.profile",
    "~/.gitconfig",
    # Windows
    "C:/Windows/",
    "C:/Program Files/",
    "C:/Program Files (x86)/",
    "C:/ProgramData/",
)


def is_system_path(path: str) -> bool:
    """是否命中系统关键路径黑名单。命中直接拒绝，不给用户确认的机会。"""
    expanded = os.path.normcase(
        str(Path(path).expanduser())
    ).replace("\\", "/")

    for critical in SYSTEM_CRITICAL_PATHS:
        normalized = os.path.normcase(
            str(Path(critical).expanduser())
        ).replace("\\", "/")
        if expanded.startswith(normalized):
            return True
        # 目录型条目也要匹配不带尾斜杠的形式（/etc 本身）
        if normalized.endswith("/") and expanded == normalized.rstrip("/"):
            return True
    return False


# 危险命令模式（09 号文档 6.1 节）。
# 相比设计文档做了三处修正：
#  1. 删掉未转义的 fork 炸弹重复项——那个正则语法上不成立，匹配行为不可预期
#  2. shutdown/reboot/halt 加了命令位置锚定，否则 `grep reboot log.txt` 会被误拦
#  3. 补上 10 号文档二节提到但 09 号漏掉的：管道到 shell、format、裸 dd if=
DANGEROUS_COMMAND_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf]{1,2}[a-zA-Z]*\s+/(\s|$)", "递归删除根目录"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\s+\*", "递归删除通配符路径"),
    (r"\bmkfs(\.|\s|$)", "格式化文件系统"),
    (r"\bformat\s+[a-zA-Z]:", "格式化磁盘分区"),
    (r"\bdd\s+if=", "裸设备写入"),
    (r":\s*\(\s*\)\s*\{.*\|\s*:.*\}\s*;\s*:", "fork 炸弹"),
    (r"\bchmod\s+-R\s+777", "递归开放全部权限"),
    (r"\bchown\s+-R\s+", "递归变更所有者"),
    (r"\|\s*(sudo\s+)?(ba)?sh\b", "管道执行下载内容"),
    (r"\b(curl|wget)\b[^|]*\|", "下载后直接执行"),
    (r"(?:^|[;&|]\s*)(sudo\s+)?(shutdown|reboot|halt|poweroff)\b", "关机/重启系统"),
    (r"\bRemove-Item\b[^\n]*\s-Recurse\b[^\n]*\s-Force\b", "PowerShell 递归强制删除"),
    (r"\b(diskpart|bcdedit)\b", "磁盘/引导配置修改"),
    (r"\bgit\s+push\b[^\n]*--force", "强制推送覆盖远端历史"),
    (r"\bgit\s+reset\s+--hard\b", "丢弃未提交的修改"),
)

_COMPILED_DANGEROUS = tuple(
    (re.compile(pattern, re.IGNORECASE), label)
    for pattern, label in DANGEROUS_COMMAND_PATTERNS
)


def is_dangerous_command(command: str) -> tuple[bool, str]:
    """命令是否命中危险模式。

    返回 ``(是否危险, 说明)``。命中即拒绝执行，不进入用户确认流程
    （10 号文档二节：不给用户"确认"的机会）。
    """
    for pattern, label in _COMPILED_DANGEROUS:
        if pattern.search(command):
            return True, label
    return False, ""


def normalize_command_allowlist(commands: Iterable[str] | None) -> tuple[str, ...]:
    """Normalize configured command names/prefixes while preserving their order."""
    if not commands:
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for command in commands:
        normalized = " ".join(str(command).strip().split()).lower()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return tuple(result)


def _shell_tokens(command: str) -> list[str] | None:
    try:
        # Commands execute in WSL, but LLMs may emit Windows host paths.
        lexer = shlex.shlex(
            command, posix=os.name != "nt", punctuation_chars=";&|><()"
        )
        lexer.whitespace_split = True
        return [_clean_shell_token(token) for token in lexer]
    except ValueError:
        return None


def _clean_shell_token(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1]
    return token


def _command_segments(tokens: list[str]) -> list[list[str]]:
    separators = {";", "&&", "||", "|", "&", "(", ")"}
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in separators:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _segment_command_name(segment: list[str]) -> str:
    for token in segment:
        if token in {">", ">>", ">|", "<", "<<", "&>", "&>>"}:
            continue
        if token.startswith("-"):
            continue
        if "=" in token and token.split("=", 1)[0].replace("_", "").isalnum():
            continue
        return Path(token).name.lower()
    return ""


def _allowlist_matches(segment: list[str], allowlist: tuple[str, ...]) -> bool:
    command_name = _segment_command_name(segment)
    if not command_name:
        return False

    command_tokens = [
        token.lower()
        for token in segment
        if token not in {">", ">>", ">|", "<", "<<", "&>", "&>>"}
    ]
    for entry in allowlist:
        entry_tokens = entry.split()
        if len(entry_tokens) == 1 and entry_tokens[0] == command_name:
            return True
        if command_tokens[: len(entry_tokens)] == entry_tokens:
            return True
    return False


def is_command_allowlisted(
    command: str, allowlist: Iterable[str] | None
) -> bool:
    """Return whether every simple command in a shell expression is allowlisted."""
    tokens = _shell_tokens(command)
    if tokens is None or not tokens:
        return False
    if "$(" in command or "`" in command:
        return False
    normalized = normalize_command_allowlist(allowlist)
    segments = _command_segments(tokens)
    return bool(segments) and all(
        _allowlist_matches(segment, normalized) for segment in segments
    )


def _command_path(path: str, workspace: str | Path) -> str:
    """Convert a WSL /mnt path to a host path before applying workspace checks."""
    normalized = path.replace("\\", "/")
    match = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", normalized)
    if match and os.name == "nt":
        tail = match.group(2) or ""
        return f"{match.group(1).upper()}:/{tail}"
    return path


def _path_is_inside_workspace(path: str, workspace: str | Path) -> bool:
    return is_safe_path(_command_path(path, workspace), workspace)


def _write_paths_from_segment(segment: list[str]) -> list[str]:
    """Extract paths for common shell writes; unknown programs remain conservative."""
    if not segment:
        return []

    paths: list[str] = []
    redirections = {">", ">>", ">|", "&>", "&>>"}
    for index, token in enumerate(segment[:-1]):
        if token in redirections:
            paths.append(segment[index + 1])

    command_name = _segment_command_name(segment)
    write_commands = {
        "chmod",
        "chown",
        "cp",
        "install",
        "ln",
        "mkdir",
        "mktemp",
        "mv",
        "rm",
        "rmdir",
        "tee",
        "touch",
        "truncate",
    }
    if command_name in write_commands:
        options = {"--", "-f", "-p", "-r", "-R", "-i", "-v", "-n", "-s"}
        paths.extend(
            token
            for token in segment[1:]
            if token not in options and not token.startswith("-")
        )
    elif command_name == "git" and len(segment) > 1 and segment[1].lower() in {
        "clone",
        "worktree",
    }:
        paths.extend(
            token
            for token in segment[2:]
            if token != "--" and not token.startswith("-")
        )
        if (
            command_name == "git"
            and segment[1].lower() == "clone"
            and len(paths) > 1
        ):
            paths = paths[-1:]
    return paths


def inspect_command_safety(
    command: str, workspace: str | Path
) -> tuple[bool, str]:
    """Check dangerous patterns and statically visible writes outside workspace."""
    dangerous, label = is_dangerous_command(command)
    if dangerous:
        return False, f"检测到危险命令（{label}）"

    tokens = _shell_tokens(command)
    if tokens is None or not tokens:
        return False, "命令语法无法安全解析"
    if "$(" in command or "`" in command:
        return False, "命令包含无法静态检查的命令替换"

    for segment in _command_segments(tokens):
        command_name = _segment_command_name(segment)
        if command_name == "cd":
            cd_index = next(
                (index for index, token in enumerate(segment) if token == "cd"), None
            )
            if cd_index is not None and cd_index + 1 < len(segment):
                target = segment[cd_index + 1]
                if not _path_is_inside_workspace(target, workspace):
                    return False, f"命令将工作目录切换到 workspace 外：{target}"

        for path in _write_paths_from_segment(segment):
            if is_system_path(_command_path(path, workspace)):
                return False, f"命令尝试写入系统关键路径：{path}"
            if not _path_is_inside_workspace(path, workspace):
                return False, f"命令尝试写入 workspace 外的路径：{path}"

    return True, ""
