"""Agent 主循环。

对应功能设计 04-Agent主循环。

同一套循环同时服务父 Agent 和子 Agent，区别只在注入的 ``MessageProvider``
和工具集（04 号文档 4.0 节）。

三条实现要点：

1. **并行工具结果必须打包成一条合成消息再写树。** ``asyncio.gather`` 并行执行
   没问题，但不能每个结果单独 append——那样一个 assistant 节点会长出 N 个子节点，
   下一条消息同时依赖这 N 个，挂在谁下面都是错的（02 号文档 2.2 节）。
2. **权限检查只在这里做一次。** 工具内部不重复检查。
3. **工具错误不中断循环。** 错误文本作为 tool_result 回给 LLM，让它自己纠错
   （08 号文档 2.2 节）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from ..errors.types import AgentError, LLMAPIError, ToolExecutionError, ValidationError
from ..llm.client import LLMClient
from ..llm.events import (
    DoneEvent,
    Message,
    STOP_REASON_TOOL_CALLS,
    TextDeltaEvent,
    ToolCall,
    ToolCallEvent,
)
from ..permission.manager import PermissionManager
from ..storage.models import ToolResultBlock
from ..tools.base import ToolResult
from ..tools.registry import ToolRegistry
from .prompts import MAIN_SYSTEM_PROMPT
from .providers import (
    EphemeralMessageProvider,
    MessageProvider,
    TreeMessageProvider,
    message_to_entry_content,
)
from .state import AgentState, RunContext, RunResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 20
MAX_SUBAGENT_DEPTH = 1

# 事件推送回调：(事件名, 载荷) -> None。由 WebSocket 层注入。
EmitFn = Callable[[str, dict], Awaitable[None]]


class Agent:
    """LLM ↔ 工具的主循环。"""

    def __init__(
        self,
        session_id: str,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        permission_manager: PermissionManager,
        provider: MessageProvider,
        workspace: Path | str = ".",
        *,
        system_prompt: Optional[str] = MAIN_SYSTEM_PROMPT,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        depth: int = 0,
        emit: Optional[EmitFn] = None,
    ) -> None:
        self.session_id = session_id
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.permission_manager = permission_manager
        self.provider = provider
        self.workspace = Path(workspace)
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        # 显式传参而不是用线程局部变量，保证并发场景下互不污染
        self.depth = depth
        self.emit = emit
        self.state = AgentState.IDLE
        self.touched_paths: list[str] = []

    # --- 事件推送 -----------------------------------------------------------

    async def _emit(self, event: str, payload: dict) -> None:
        if self.emit is None:
            return
        try:
            await self.emit(event, payload)
        except Exception:  # noqa: BLE001 - 推送失败不能影响主流程
            logger.warning("推送事件 %s 失败", event, exc_info=True)

    async def _set_state(self, state: AgentState) -> None:
        self.state = state
        await self._emit("status_update", {
            "state": state.value,
            "current_lane": getattr(self.provider, "lane", None),
            "current_operation": self._get_operation_label(state)
        })

    def _get_operation_label(self, state: AgentState) -> str | None:
        """将状态转换为用户友好的操作描述。"""
        labels = {
            AgentState.CALLING_LLM: "正在思考",
            AgentState.EXECUTING_TOOL: "正在执行工具",
            AgentState.WAITING_PERMISSION: "等待权限确认",
        }
        return labels.get(state)

    # --- 主循环 -------------------------------------------------------------

    async def run(
        self,
        user_message: Optional[str] = None,
        max_steps: Optional[int] = None,
    ) -> RunResult:
        """执行一次完整的 run。

        ``user_message`` 为 None 时跳过"追加用户消息"这一步——子 Agent 的任务
        描述已经由 ``EphemeralMessageProvider`` 种进上下文了。
        """
        started = time.time()
        limit = max_steps if max_steps is not None else self.max_iterations
        ctx = RunContext(
            lane=getattr(self.provider, "lane", "main"), state=AgentState.PREPARING
        )
        await self._emit("run_started", {"run_id": ctx.run_id, "lane": ctx.lane})
        await self._set_state(AgentState.PREPARING)

        try:
            if user_message is not None:
                ctx.user_message_id = await self.provider.append(
                    Message(role="user", content=user_message)
                )
                if ctx.user_message_id:
                    await self._emit(
                        "node_added",
                        {"id": ctx.user_message_id, "role": "user", "lane": ctx.lane},
                    )

            result = await self._iterate(ctx, limit, started)
            await self._emit(
                "run_completed",
                {
                    "run_id": ctx.run_id,
                    "status": result.status,
                    "iterations": result.iterations,
                    "total_tokens": result.total_tokens,
                    "duration": result.duration,
                },
            )
            await self._set_state(AgentState.IDLE)
            return result

        except AgentError as exc:
            logger.error("run 失败: %s", exc.message)
            await self._set_state(AgentState.ERROR)
            await self._emit(
                "run_error",
                {
                    "run_id": ctx.run_id,
                    "code": exc.code,
                    "message": exc.message,
                    "error": exc.message,
                    "retryable": getattr(exc, "retryable", False),
                    "suggestions": getattr(exc, "suggestions", []),
                },
            )
            return RunResult(
                run_id=ctx.run_id,
                status="error",
                iterations=ctx.iteration,
                total_tokens=ctx.total_tokens,
                duration=time.time() - started,
                error=exc.message,
                touched_paths=list(self.touched_paths),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("run 出现未预期错误")
            await self._set_state(AgentState.ERROR)
            await self._emit(
                "run_error",
                {
                    "run_id": ctx.run_id,
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "error": str(exc),
                    "retryable": False,
                    "suggestions": [],
                },
            )
            return RunResult(
                run_id=ctx.run_id,
                status="error",
                iterations=ctx.iteration,
                total_tokens=ctx.total_tokens,
                duration=time.time() - started,
                error=f"{exc.__class__.__name__}: {exc}",
                touched_paths=list(self.touched_paths),
            )

    async def _iterate(
        self, ctx: RunContext, limit: int, started: float
    ) -> RunResult:
        final_text = ""
        final_id: Optional[str] = None
        tools = self.tool_registry.get_tool_schemas()

        while ctx.iteration < limit:
            ctx.iteration += 1
            await self._set_state(AgentState.CALLING_LLM)

            messages = self._build_messages()
            await self._emit("context_loaded", {
                "message_count": len(messages),
                "total_tokens": sum(len(m.content or "") // 4 for m in messages)
            })

            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            stop_reason = "stop"

            message_id = f"{ctx.run_id}-{ctx.iteration}"
            await self._emit("message_start", {"message_id": message_id})

            # 记录 LLM 请求
            await self._emit("llm_request", {
                "provider": self.llm_client.provider_name,
                "model": self.llm_client.model,
                "input_tokens": sum(len(m.content or "") // 4 for m in messages)
            })

            async for event in self.llm_client.chat(messages, tools or None):
                if isinstance(event, TextDeltaEvent):
                    text_parts.append(event.text)
                    await self._emit(
                        "text_delta", {"message_id": message_id, "text": event.text}
                    )
                elif isinstance(event, ToolCallEvent):
                    tool_calls.append(
                        ToolCall(
                            id=event.id or f"call_{ctx.iteration}_{len(tool_calls)}",
                            name=event.name,
                            arguments=event.arguments,
                        )
                    )
                elif isinstance(event, DoneEvent):
                    stop_reason = event.stop_reason
                    ctx.total_tokens += int(event.usage.get("total_tokens") or 0)
                    # 记录 LLM 响应
                    await self._emit("llm_response", {
                        "stop_reason": stop_reason,
                        "output_tokens": int(event.usage.get("completion_tokens") or 0),
                        "total_tokens": int(event.usage.get("total_tokens") or 0)
                    })

            assistant_text = "".join(text_parts)
            if assistant_text:
                final_text = assistant_text

            # assistant 消息落树（含工具调用请求）
            assistant_msg = Message(
                role="assistant",
                content=assistant_text or None,
                tool_calls=tool_calls or None,
            )
            node_id = await self._append_assistant(assistant_msg)
            if node_id:
                final_id = node_id
                await self._emit(
                    "node_added",
                    {
                        "id": node_id,
                        "role": "assistant",
                        "lane": ctx.lane,
                        "message_id": message_id,
                    },
                )
            await self._emit(
                "message_end", {"message_id": message_id, "stop_reason": stop_reason}
            )

            if not tool_calls:
                # 没有工具调用即对话结束，无论 stop_reason 是什么
                return RunResult(
                    run_id=ctx.run_id,
                    status="completed",
                    final_message_id=final_id,
                    final_text=final_text,
                    iterations=ctx.iteration,
                    total_tokens=ctx.total_tokens,
                    duration=time.time() - started,
                    touched_paths=list(self.touched_paths),
                )

            await self._set_state(AgentState.EXECUTING_TOOL)
            blocks = await self._execute_tool_calls(tool_calls, ctx)

            # 关键：N 个工具结果打包成一条消息，不是 N 条
            tool_node_id = await self._append_tool_results(blocks)
            if tool_node_id:
                await self._emit(
                    "node_added",
                    {"id": tool_node_id, "role": "tool", "lane": ctx.lane},
                )

            if stop_reason not in (STOP_REASON_TOOL_CALLS, "stop"):
                logger.info("stop_reason=%s，继续下一轮", stop_reason)

        # 迭代用尽：属于警告而非错误，已完成的工作要保留
        logger.warning("达到最大迭代次数 %d，强制结束", limit)
        return RunResult(
            run_id=ctx.run_id,
            status="partial",
            final_message_id=final_id,
            final_text=final_text,
            iterations=ctx.iteration,
            total_tokens=ctx.total_tokens,
            duration=time.time() - started,
            touched_paths=list(self.touched_paths),
            error=f"达到最大迭代次数 {limit}",
        )

    def _build_messages(self) -> list[Message]:
        messages = self.provider.get_context()
        if self.system_prompt and not any(m.role == "system" for m in messages):
            return [Message(role="system", content=self.system_prompt)] + messages
        return messages

    async def _append_assistant(self, message: Message) -> Optional[str]:
        if isinstance(self.provider, TreeMessageProvider):
            return await self.provider.append_entry(
                role="assistant", content=message_to_entry_content(message)
            )
        return await self.provider.append(message)

    async def _append_tool_results(
        self, blocks: list[ToolResultBlock]
    ) -> Optional[str]:
        if isinstance(self.provider, TreeMessageProvider):
            return await self.provider.append_entry(role="tool", content=list(blocks))
        # 内存实现按协议形态逐条追加即可，没有树结构约束
        if isinstance(self.provider, EphemeralMessageProvider):
            for block in blocks:
                self.provider.append_sync(
                    Message(
                        role="tool",
                        content=block.content,
                        tool_call_id=block.tool_call_id,
                    )
                )
            return None
        for block in blocks:
            await self.provider.append(
                Message(
                    role="tool", content=block.content, tool_call_id=block.tool_call_id
                )
            )
        return None

    # --- 工具执行 -----------------------------------------------------------

    async def _execute_tool_calls(
        self, tool_calls: list[ToolCall], ctx: RunContext
    ) -> list[ToolResultBlock]:
        """并行执行所有工具调用，返回结果块列表（顺序与请求一致）。"""
        results = await asyncio.gather(
            *(self._execute_one(tc, ctx) for tc in tool_calls)
        )
        return list(results)

    async def _execute_one(
        self, call: ToolCall, ctx: RunContext
    ) -> ToolResultBlock:
        """执行单个工具调用：权限检查 → 执行 → 转成结果块。

        每个协程内部自己兜住异常，不依赖 ``gather(return_exceptions=True)``——
        默认行为下一个任务抛异常会取消其他还在跑的协程，这是常见的坑
        （15 号文档 7.2 节）。
        """
        await self._emit(
            "tool_call_start",
            {"call_id": call.id, "tool_name": call.name, "args": call.arguments},
        )
        ctx.tool_calls.append({"name": call.name, "args": call.arguments})

        try:
            decision = await self._check_permission(call)
            if not decision.allowed:
                content = (
                    f"权限不足，操作未执行: {decision.reason}\n\n"
                    "如果这个操作确有必要，请向用户说明理由，或换一种不需要该权限的做法。"
                )
                await self._emit(
                    "tool_call_end",
                    {"call_id": call.id, "status": "error", "result": decision.reason},
                )
                return ToolResultBlock(
                    tool_call_id=call.id, content=content, is_error=True
                )

            result = await self.tool_registry.execute(call.name, call.arguments)
            self._track_path(call)

            await self._emit(
                "tool_call_end",
                {
                    "call_id": call.id,
                    "status": "error" if result.is_error else "success",
                    "result": result.content[:500],
                    "metadata": result.metadata,
                },
            )
            return ToolResultBlock(
                tool_call_id=call.id,
                content=result.to_llm_text(),
                is_error=result.is_error,
            )

        except (ToolExecutionError, ValidationError) as exc:
            logger.warning("工具 %s 执行失败: %s", call.name, exc.message)
            await self._emit(
                "tool_call_end",
                {"call_id": call.id, "status": "error", "result": exc.message},
            )
            return ToolResultBlock(
                tool_call_id=call.id, content=exc.to_llm_message(), is_error=True
            )
        except LLMAPIError:
            # 子 Agent 内部的 LLM 错误要往上冒，不能当成普通工具失败吞掉
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("工具 %s 出现未预期错误", call.name)
            await self._emit(
                "tool_call_end",
                {"call_id": call.id, "status": "error", "result": str(exc)},
            )
            return ToolResultBlock(
                tool_call_id=call.id,
                content=f"工具 {call.name} 执行时出现未预期错误: {exc}",
                is_error=True,
            )

    async def _check_permission(self, call: ToolCall):
        tool = self.tool_registry.get_tool(call.name)
        if tool is None:
            # 交给 registry.execute 抛 TOOL_NOT_FOUND，错误信息更完整
            from ..permission.manager import PermissionDecision

            return PermissionDecision(allowed=True, reason="工具不存在，交由执行层报错")

        needs_confirm = tool.permission_level.value != "safe"
        if needs_confirm:
            await self._set_state(AgentState.WAITING_PERMISSION)
        decision = await self.permission_manager.check(call.name, call.arguments)
        if needs_confirm:
            await self._set_state(AgentState.EXECUTING_TOOL)
        return decision

    def _track_path(self, call: ToolCall) -> None:
        """记录被访问的文件，供子 Agent 的 details 汇报使用。"""
        path = call.arguments.get("path")
        if isinstance(path, str) and path and path not in self.touched_paths:
            self.touched_paths.append(path)
