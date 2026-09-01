"""权限闸门。

对应功能设计 09-权限控制系统 三节。

设计原则（09 号文档一节）：默认安全——不确定就问用户；最小权限；透明可控。

权限检查只发生在**工具执行入口**（``Agent._execute_tool_calls``），工具内部
不重复检查。子 Agent 用的是同一个 PermissionManager 实例，不因为调用方是子
Agent 就绕开检查（15 号文档八节的硬约束）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Optional

from ..config import DEFAULT_COMMAND_BLACKLIST
from .rules import (
    inspect_command_safety,
    is_command_blacklisted,
    is_safe_path,
    is_system_path,
    normalize_command_blacklist,
)

logger = logging.getLogger(__name__)


class PermissionLevel(str, Enum):
    SAFE = "safe"
    WRITE = "write"
    DANGEROUS = "dangerous"


# 工具 → 权限级别（09 号文档 2.2 节矩阵）。
# 未登记的工具默认按 DANGEROUS 处理——失败时偏保守，不是偏放行。
TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    "read_file": PermissionLevel.SAFE,
    "glob": PermissionLevel.SAFE,
    "grep": PermissionLevel.SAFE,
    "list_directory": PermissionLevel.SAFE,
    "web_search": PermissionLevel.SAFE,
    "web_fetch": PermissionLevel.SAFE,
    "write_file": PermissionLevel.WRITE,
    "edit_file": PermissionLevel.WRITE,
    "bash": PermissionLevel.DANGEROUS,
    # 子 Agent 只能用只读工具，本身不产生副作用，所以是 SAFE（15 号文档五节）。
    # 如果哪天放开了写权限，这个级别必须同步上调。
    "delegate_task": PermissionLevel.SAFE,
}

RiskLevel = str  # "low" | "medium" | "high"

# PermissionLevel → 前端契约的 risk_level（代码设计 02 号文档 3.2 节）。
_LEVEL_TO_RISK: dict[str, RiskLevel] = {
    PermissionLevel.SAFE.value: "low",
    PermissionLevel.WRITE.value: "medium",
    PermissionLevel.DANGEROUS.value: "high",
}


def normalize_risk_level(value: str) -> RiskLevel:
    """把权限层的风险取值折叠成前端契约的 low/medium/high。

    `_ask_user` 传出的本来就是 low/medium/high，直接透传；同时兼容按
    PermissionLevel 名字（safe/write/dangerous）传入的调用点。两者不加区分地
    塞进同一张映射表会让 high 被静默降级成 medium，所以先判透传再查表。
    """
    if value in ("low", "medium", "high"):
        return value
    return _LEVEL_TO_RISK.get(value, "medium")


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str
    user_confirmed: bool = False
    auto_approved: bool = False


class PermissionManager:
    """三级权限判定 + 用户确认闸门 + 决策记忆。"""

    def __init__(self, workspace: str | Path, config: Optional[dict] = None) -> None:
        self.workspace = str(Path(workspace).expanduser().resolve())
        self.config = config or {}
        self.command_blacklist = normalize_command_blacklist(
            self.config.get("command_blacklist", DEFAULT_COMMAND_BLACKLIST)
        )
        self.auto_approved: set[str] = set()
        self.denied: set[str] = set()
        # 由 WebSocket 层注入。未注入时需要确认的高风险操作一律拒绝。
        self.ask_user_callback: Optional[Callable[[dict], Awaitable[dict]]] = None
        self.audit_log: list[dict] = []

    def set_workspace(self, workspace: str | Path) -> str:
        """Rebind path and command checks to the active Lane workspace."""
        self.workspace = str(Path(workspace).expanduser().resolve())
        return self.workspace

    async def check(self, tool_name: str, args: dict) -> PermissionDecision:
        """判定一次工具调用是否放行。

        顺序是有讲究的：先查用户既有决策（拒绝优先于放行），再按级别分派。
        用户的显式决策优先于级别规则。
        """
        level = TOOL_PERMISSIONS.get(tool_name, PermissionLevel.DANGEROUS)
        fingerprint = self._fingerprint(tool_name, args)

        decision = await self._decide(tool_name, args, level, fingerprint)
        self._audit(tool_name, args, level, decision)
        return decision

    async def _decide(
        self,
        tool_name: str,
        args: dict,
        level: PermissionLevel,
        fingerprint: str,
    ) -> PermissionDecision:
        if fingerprint in self.denied:
            return PermissionDecision(allowed=False, reason="用户之前拒绝了此操作")
        if level is PermissionLevel.DANGEROUS:
            return await self._check_dangerous(tool_name, args, fingerprint)
        if fingerprint in self.auto_approved:
            return PermissionDecision(
                allowed=True, reason="自动批准（用户之前选择总是允许）", auto_approved=True
            )
        if level is PermissionLevel.SAFE:
            return PermissionDecision(
                allowed=True, reason="只读操作，自动允许", auto_approved=True
            )
        if level is PermissionLevel.WRITE:
            return await self._check_write(tool_name, args, fingerprint)
        return await self._check_dangerous(tool_name, args, fingerprint)

    async def _check_write(
        self, tool_name: str, args: dict, fingerprint: str
    ) -> PermissionDecision:
        """WRITE 级：workspace 内自动放行，系统路径硬拒绝，越界需确认。"""
        path = args.get("path") or ""
        if not path:
            return PermissionDecision(allowed=False, reason="未提供文件路径")

        # 系统关键路径优先于"越界确认"判断：这类路径绝不放行，
        # 也不该弹窗给用户一个点"允许"的机会。
        if is_system_path(path):
            return PermissionDecision(
                allowed=False, reason=f"不允许写入系统关键路径: {path}"
            )

        if not is_safe_path(path, self.workspace):
            return await self._ask_user(
                tool_name=tool_name,
                args=args,
                risk_level="medium",
                warning=f"将写入工作目录外的文件: {path}",
                fingerprint=fingerprint,
            )

        return PermissionDecision(
            allowed=True, reason="路径在工作目录内", auto_approved=True
        )

    async def _check_dangerous(
        self, tool_name: str, args: dict, fingerprint: str
    ) -> PermissionDecision:
        """DANGEROUS 级：命中黑名单拒绝，其余安全命令自动放行。"""
        command = args.get("command") or ""

        safe, safety_reason = inspect_command_safety(command, self.workspace)
        blacklisted, blacklist_reason = is_command_blacklisted(
            command, self.command_blacklist
        )
        if blacklisted:
            return PermissionDecision(
                allowed=False,
                reason=f"命令命中黑名单：{blacklist_reason}",
            )
        if safe:
            return PermissionDecision(
                allowed=True,
                reason="命令未命中黑名单且通过安全检查",
                auto_approved=True,
            )

        if fingerprint in self.auto_approved:
            return PermissionDecision(
                allowed=True,
                reason="自动批准（用户之前选择总是允许）",
                auto_approved=True,
            )

        warning = "此操作将执行 shell 命令"
        if not safe:
            warning = f"命令存在风险，需要用户确认：{safety_reason}"

        return await self._ask_user(
            tool_name=tool_name,
            args=args,
            risk_level="high",
            warning=warning,
            fingerprint=fingerprint,
        )

    def get_command_blacklist(self) -> list[str]:
        return list(self.command_blacklist)

    def set_command_blacklist(self, commands: list[str]) -> list[str]:
        self.command_blacklist = normalize_command_blacklist(commands)
        self.config["command_blacklist"] = list(self.command_blacklist)
        return self.get_command_blacklist()


    async def _ask_user(
        self,
        tool_name: str,
        args: dict,
        risk_level: RiskLevel,
        warning: str,
        fingerprint: Optional[str] = None,
    ) -> PermissionDecision:
        """向用户请求确认。没有回调时默认拒绝（fail-closed）。"""
        if self.ask_user_callback is None:
            return PermissionDecision(
                allowed=False, reason="需要用户确认但未配置确认机制"
            )

        response = await self.ask_user_callback(
            {
                "tool_name": tool_name,
                "args": args,
                "risk_level": risk_level,
                "warning": warning,
            }
        )
        action = (response or {}).get("action", "deny")

        if action == "allow_once":
            return PermissionDecision(
                allowed=True, reason="用户允许（仅本次）", user_confirmed=True
            )
        if action == "allow_always":
            if fingerprint:
                self.auto_approved.add(fingerprint)
            return PermissionDecision(
                allowed=True,
                reason="用户允许（总是）",
                user_confirmed=True,
                auto_approved=True,
            )

        if fingerprint:
            self.denied.add(fingerprint)
        return PermissionDecision(allowed=False, reason="用户拒绝了此操作")

    def _fingerprint(self, tool_name: str, args: dict) -> str:
        """操作指纹（09 号文档 3.1 节）。

        只取 path/command 两个关键参数，command 截断到 50 字符——
        这样"同一个操作换了个无关参数"不会被当成新操作重复弹窗。
        """
        key_args: dict = {}
        if "path" in args:
            key_args["path"] = args["path"]
        if "command" in args:
            key_args["command"] = str(args["command"])[:50]
        payload = f"{tool_name}:{json.dumps(key_args, sort_keys=True, ensure_ascii=False)}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    def _audit(
        self,
        tool_name: str,
        args: dict,
        level: PermissionLevel,
        decision: PermissionDecision,
    ) -> None:
        """记录审计条目（09 号文档 7.1 节）。"""
        from datetime import datetime

        self.audit_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "event": "permission_decision",
                "tool": tool_name,
                "args": args,
                "level": level.value,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "user_confirmed": decision.user_confirmed,
                "auto_approved": decision.auto_approved,
            }
        )

    def get_audit_log(self) -> list[dict]:
        return list(self.audit_log)

    def audit_report(self) -> dict:
        """聚合审计报告（09 号文档 7.2 节）。

        `recent_denials` 只保留最近 10 条被拒决策——审计面板要的是"最近出了
        什么问题"，不是完整流水；完整流水走 get_audit_log()。
        """
        tool_breakdown: dict[str, int] = {}
        allowed = denied = user_confirmed = auto_approved = 0
        denials: list[dict] = []

        for item in self.audit_log:
            tool = item.get("tool", "unknown")
            tool_breakdown[tool] = tool_breakdown.get(tool, 0) + 1
            if item.get("allowed"):
                allowed += 1
            else:
                denied += 1
                denials.append(item)
            if item.get("user_confirmed"):
                user_confirmed += 1
            if item.get("auto_approved"):
                auto_approved += 1

        return {
            "total_decisions": len(self.audit_log),
            "allowed": allowed,
            "denied": denied,
            "user_confirmed": user_confirmed,
            "auto_approved": auto_approved,
            "tool_breakdown": tool_breakdown,
            "recent_denials": denials[-10:],
        }

    def reset(self) -> None:
        """清空记忆的决策。"""
        self.auto_approved.clear()
        self.denied.clear()
