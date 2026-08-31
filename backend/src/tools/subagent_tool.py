"""子 Agent 委托工具。

对应功能设计 15-子Agent系统（13 号文档已将其上调为 P1）。

子 Agent 的定位是"侦察兵"而不是"执行者"：只读工具集、独立上下文、
深度硬限制 1 层、结果只回一段结论。即使无人盯着它跑，风险也天然可控。

结果走**双通道**（15 号文档 7.1 节）：
- ``content`` 是给父 LLM 的结论，占父上下文的 token
- ``details`` 只给前端卡片看，不进父 LLM 上下文
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..llm.client import LLMClient
from ..llm.events import Message
from ..permission.manager import PermissionManager
from .base import Tool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 8
# wall-clock 兜底：步数预算防不住单步卡死（比如一个卡住的工具调用）
SUBAGENT_TIMEOUT = 120
# 仅用于提示和 UI 标记，不作为硬截断阈值
SUMMARY_SOFT_LIMIT = 2000


class DelegateTaskTool(Tool):
    name = "delegate_task"
    description = (
        "把一个需要多步调查才能有结论的子任务委托给独立的子 Agent 去做。"
        "子 Agent 只能使用只读工具（读文件、搜索），完成后只返回一段结论摘要，"
        "不会把中间过程带回来。适合『帮我确认 XXX』『帮我调查 XXX 有没有问题』这类任务。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "交给子 Agent 的任务描述，要包含足够的背景信息",
            },
            "max_steps": {
                "type": "integer",
                "description": f"子 Agent 最多执行的工具调用轮数，默认 {DEFAULT_MAX_STEPS}",
            },
        },
        "required": ["task"],
    }

    def __init__(
        self,
        session_id: str,
        workspace: Path | str,
        llm_client: LLMClient,
        permission_manager: PermissionManager,
        depth: int = 0,
        emit=None,
    ) -> None:
        self.session_id = session_id
        self.workspace = Path(workspace)
        self.llm_client = llm_client
        # 和父 Agent 共用同一个 PermissionManager：不能因为套了一层子 Agent
        # 就绕开权限检查（15 号文档八节的硬约束）
        self.permission_manager = permission_manager
        self.depth = depth
        self.emit = emit
        self._semaphore = asyncio.Semaphore(3)
        self._counter = 0

    async def execute(  # type: ignore[override]
        self, task: str, max_steps: int = DEFAULT_MAX_STEPS
    ) -> ToolResult:
        from ..agent.loop import MAX_SUBAGENT_DEPTH, Agent
        from ..agent.prompts import SUBAGENT_SYSTEM_PROMPT, SUBAGENT_WRAPUP_PROMPT
        from ..agent.providers import EphemeralMessageProvider
        from .registry import ToolRegistry

        if self.depth >= MAX_SUBAGENT_DEPTH:
            # 能力上的硬限制，不是配置项
            return ToolResult.error(
                "子 Agent 不允许递归派生",
                suggestions=["在当前层级直接用只读工具完成调查"],
            )
        if not task or not task.strip():
            return ToolResult.error("task 不能为空")

        max_steps = max(1, min(int(max_steps), 20))
        self._counter += 1
        subagent_id = f"sub-{self._counter}"

        await self._emit(
            "subagent_started",
            {
                "subagent_id": subagent_id,
                "task": task,
                "max_steps": max_steps,
                "status": "pending",
            },
        )

        provider = EphemeralMessageProvider(
            seed_task=task, system_prompt=SUBAGENT_SYSTEM_PROMPT
        )
        sub_agent = Agent(
            session_id=self.session_id,  # 仅用于日志标识，不读写树
            llm_client=self.llm_client,
            tool_registry=ToolRegistry.readonly(self.workspace),
            permission_manager=self.permission_manager,
            provider=provider,
            workspace=self.workspace,
            system_prompt=None,  # 已经种进 provider 了
            max_iterations=max_steps,
            depth=self.depth + 1,
            emit=self._make_progress_emitter(subagent_id, max_steps),
        )

        try:
            async with self._semaphore:
                result = await asyncio.wait_for(
                    sub_agent.run(max_steps=max_steps), timeout=SUBAGENT_TIMEOUT
                )
        except asyncio.TimeoutError:
            await self._emit(
                "subagent_done",
                {
                    "subagent_id": subagent_id,
                    "status": "error",
                    "content": "子 Agent 超时",
                    "details": {"error": f"超过 {SUBAGENT_TIMEOUT} 秒"},
                },
            )
            return ToolResult.error(
                f"子 Agent 执行超时（{SUBAGENT_TIMEOUT} 秒），任务未完成",
                suggestions=["把任务拆得更具体一些再委托", "或在当前层级直接调查"],
            )
        except Exception as exc:  # noqa: BLE001 - 异常必须在这里兜住
            logger.exception("子 Agent 执行失败")
            await self._emit(
                "subagent_done",
                {
                    "subagent_id": subagent_id,
                    "status": "error",
                    "content": str(exc),
                    "details": {"error": str(exc)},
                },
            )
            return ToolResult.error(f"子 Agent 执行失败: {exc}")

        # 步数用尽时不硬切半截话，而是追加一轮收尾调用让它自己总结
        if result.status == "partial" and result.final_text.strip() == "":
            summary = await self._force_wrapup(provider, SUBAGENT_WRAPUP_PROMPT)
            if summary:
                result.final_text = summary

        return await self._package(result, subagent_id)

    async def _force_wrapup(self, provider, wrapup_prompt: str) -> str:
        """强制追加一轮 tool_choice=none 的收尾调用（15 号文档 6.2 节）。

        目的是让子 Agent 自己总结，而不是硬切一段可能没说完的话。
        """
        from ..llm.events import DoneEvent, TextDeltaEvent

        provider.append_sync(Message(role="user", content=wrapup_prompt))
        parts: list[str] = []
        try:
            async for event in self.llm_client.chat(
                provider.get_context(), None, tool_choice="none"
            ):
                if isinstance(event, TextDeltaEvent):
                    parts.append(event.text)
                elif isinstance(event, DoneEvent):
                    break
        except Exception:  # noqa: BLE001
            logger.warning("子 Agent 收尾调用失败", exc_info=True)
            return ""
        return "".join(parts)

    async def _package(self, result, subagent_id: str) -> ToolResult:
        """双通道打包（15 号文档 7.1 节）。"""
        summary = (result.final_text or "").strip()
        if not summary:
            summary = "子 Agent 没有产出结论。"
        summary_over_limit = len(summary) > SUMMARY_SOFT_LIMIT

        status = result.status
        if status == "error":
            content = f"[error] 子 Agent 未能完成调查: {result.error or '未知原因'}"
        else:
            # status 让父 LLM 知道结论是否因预算耗尽而不完整，该不该谨慎采信
            content = f"[{status}] {summary}"

        details = {
            "subagent_id": subagent_id,
            "tool_calls": result.iterations,
            "files_touched": result.touched_paths,
            "duration": round(result.duration, 2),
            "total_tokens": result.total_tokens,
            "summary_length": len(summary),
            "summary_over_limit": summary_over_limit,
        }

        await self._emit(
            "subagent_done",
            {
                "subagent_id": subagent_id,
                "status": status,
                "content": content,
                "details": details,
            },
        )

        return ToolResult(
            content=content, is_error=(status == "error"), metadata=details
        )

    def _make_progress_emitter(self, subagent_id: str, max_steps: int):
        """把子 Agent 的内部事件转成 subagent_progress。

        子 Agent 的中间步骤只走这个通道给前端看，绝不进父树
        （15 号文档 6.2 节：这是子 Agent 存在的意义所在）。
        """
        if self.emit is None:
            return None

        step = {"n": 0}

        async def _emit_progress(event: str, payload: dict) -> None:
            if event == "tool_call_start":
                step["n"] += 1
                await self._emit(
                    "subagent_progress",
                    {
                        "subagent_id": subagent_id,
                        "status": "running",
                        "step": step["n"],
                        "max_steps": max_steps,
                        "tool_name": payload.get("tool_name"),
                        "message": f"正在调用 {payload.get('tool_name') or '工具'}",
                    },
                )

        return _emit_progress

    async def _emit(self, event: str, payload: dict) -> None:
        if self.emit is None:
            return
        try:
            await self.emit(event, payload)
        except Exception:  # noqa: BLE001
            logger.warning("推送子 Agent 事件失败", exc_info=True)
