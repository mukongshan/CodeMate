"""权限判定的纯函数：路径安全、危险命令识别。

对应功能设计 09-权限控制系统 五、六节。

单独成文件（不和 PermissionManager 混在一起）是为了能独立做单元测试——
这些函数是安全边界，必须能穷举测试用例。
"""

from __future__ import annotations

import os
import re
from pathlib import Path


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
