"""会话服务：把存储、LLM、工具、权限、Agent 装配成一个可用的会话。

对应代码设计 02 号文档、03 号文档九节。

一个 ``SessionRuntime`` 对应一个 session。执行模型上有一条硬约束
（03 号文档 7.3 节）：**任意时刻只有一个 Lane 在跑**，所以运行锁是
session 级的，不按 Lane 分。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Awaitable, Callable, Optional

from ..agent.loop import Agent
from ..agent.prompts import MAIN_SYSTEM_PROMPT
from ..agent.providers import TreeMessageProvider
from ..agent.state import AgentState, RunResult
from ..config import AppConfig
from ..errors.types import AgentError
from ..llm.client import LLMClient
from ..observability.logger import StructuredLogger
from ..permission.manager import PermissionManager, normalize_risk_level
from ..storage.lane_manager import LaneManager
from ..storage.session_storage import SessionStorage
from ..tools.registry import ToolRegistry
from ..tools.subagent_tool import DelegateTaskTool
from ..version_control import GitLaneManager

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, dict], Awaitable[None]]


class SessionBusyError(RuntimeError):
    """当前 session 已有 run 在执行。"""


class SessionRuntime:
    """单个会话的完整运行时。"""

    def __init__(self, session_id: str, config: AppConfig) -> None:
        self.session_id = session_id
        self.config = config
        self.storage = SessionStorage(session_id, config.data_dir)
        self.lane_manager = LaneManager(session_id, config.data_dir)
        self.git_manager = GitLaneManager(
            session_id=session_id,
            source_workspace=config.workspace,
            data_dir=config.data_dir,
            worktree_root=config.worktree_root,
            max_file_bytes=config.checkpoint_max_file_bytes,
            checkpoint_merge_window_seconds=config.checkpoint_merge_window_seconds,
            checkpoint_max_pending_runs=config.checkpoint_max_pending_runs,
            checkpoint_max_pending_files=config.checkpoint_max_pending_files,
            checkpoint_max_pending_seconds=config.checkpoint_max_pending_seconds,
        )
        if self.git_manager.enabled:
            for pointer in self.lane_manager.list_lanes():
                if not self.git_manager.has_binding(pointer.lane):
                    self.git_manager.ensure_legacy_lane(pointer.lane)
            self.git_manager.reconcile_operations(
                {pointer.lane for pointer in self.lane_manager.list_lanes()}
            )
        self.log = StructuredLogger(session_id, config.log_dir)
        active_workspace = self.workspace_for_lane(self.lane_manager.current_lane)
        self.permission_manager = PermissionManager(
            workspace=active_workspace,
            config={"command_allowlist": config.command_allowlist},
        )
        self.llm_client: LLMClient = LLMClient.from_config(config.llm.to_client_dict())
        self._run_lock = asyncio.Lock()
        self._emit: Optional[EmitFn] = None
        self._emitter_token: Optional[str] = None
        self._pending_permissions: dict[str, asyncio.Future] = {}
        self._active_run_task: Optional[asyncio.Task] = None
        self._active_run_id: Optional[str] = None
        self._interrupt_requested = False
        self._checkpoint_flush_tasks: dict[str, asyncio.Task] = {}
        self.state = AgentState.IDLE

        self.log.info(
            "agent_started",
            workspace=str(active_workspace),
            source_workspace=str(config.workspace),
            git_enabled=self.git_manager.enabled,
            provider=config.llm.provider,
            model=config.llm.model,
        )

    # --- 连接管理 -----------------------------------------------------------

    def set_emitter(self, emit: EmitFn, token: str) -> None:
        self._emit = emit
        self._emitter_token = token
        self.permission_manager.ask_user_callback = self._ask_user

    def clear_emitter(self, token: str) -> bool:
        if self._emitter_token != token:
            return False
        self._emit = None
        self._emitter_token = None
        self.permission_manager.ask_user_callback = None
        return True

    async def emit(self, event: str, payload: dict) -> None:
        payload = dict(payload)
        event_lane = payload.get("lane") or payload.get("parent_lane")
        if event_lane is None:
            event_lane = self.lane_manager.current_lane
        payload.setdefault("lane", event_lane)
        if event.startswith("subagent_"):
            payload.setdefault("parent_lane", event_lane)
        if event == "run_started":
            self._active_run_id = payload.get("run_id")
        if event == "status_update":
            try:
                self.state = AgentState(payload.get("state", "idle"))
            except ValueError:
                pass
        if self._emit is None:
            return
        await self._emit(event, payload)

    async def _ask_user(self, request: dict) -> dict:
        """把权限请求推给前端，挂起等待用户回复。

        用 Future 而不是轮询：主循环 await 在这里，直到 ws 层收到
        `permission_response` 调用 resolve_permission() 把 Future 填上。
        弹窗不自动消失、没有倒计时（07 号文档 8.1 节），所以这里也不设超时——
        但连接断开时必须兜底，否则 run 会永久挂起，见 fail_pending_permissions()。
        """
        request_id = f"perm_{uuid.uuid4().hex[:8]}"
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending_permissions[request_id] = future

        await self.emit(
            "permission_request",
            {
                "request_id": request_id,
                "tool_name": request.get("tool_name", ""),
                "args": request.get("args", {}),
                "risk_level": normalize_risk_level(request.get("risk_level", "")),
                "warning": request.get("warning", ""),
            },
        )
        try:
            return await future
        finally:
            self._pending_permissions.pop(request_id, None)

    def resolve_permission(self, request_id: str, action: str) -> bool:
        """由 ws 层在收到 permission_response 时调用。返回是否命中一个等待中的请求。"""
        future = self._pending_permissions.get(request_id)
        if future is None or future.done():
            return False
        future.set_result({"action": action})
        return True

    def fail_pending_permissions(self, reason: str = "连接已断开") -> None:
        """连接断开时把所有挂起的权限请求判为拒绝。

        默认安全（09 号文档一节）：拿不到用户确认就当拒绝，绝不放过。
        """
        for request_id, future in list(self._pending_permissions.items()):
            if not future.done():
                future.set_result({"action": "deny", "reason": reason})
            self._pending_permissions.pop(request_id, None)

    # --- 执行 ---------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._run_lock.locked()

    async def interrupt_run(self, run_id: Optional[str] = None) -> bool:
        task = self._active_run_task
        if task is None or task.done() or self._interrupt_requested:
            return False
        if run_id and self._active_run_id and run_id != self._active_run_id:
            return False

        self._interrupt_requested = True
        await self.emit(
            "run_interrupt_requested",
            {"run_id": self._active_run_id, "status": "interrupting"},
        )
        self.fail_pending_permissions("用户已中断当前运行")
        task.cancel("用户中断")
        return True

    def build_agent(self, lane: str) -> Agent:
        if self.git_manager.enabled:
            self.git_manager.ensure_lane_ready(lane)
        workspace = self.workspace_for_lane(lane)
        self.permission_manager.set_workspace(workspace)
        registry = ToolRegistry.default(workspace)
        registry.register(
            DelegateTaskTool(
                session_id=self.session_id,
                workspace=workspace,
                llm_client=self.llm_client,
                permission_manager=self.permission_manager,
                depth=0,
                emit=self.emit,
            )
        )
        provider = TreeMessageProvider(
            storage=self.storage,
            lane_manager=self.lane_manager,
            lane=lane,
            max_context_tokens=self.config.max_context_tokens,
        )
        system_prompt = (
            f"{MAIN_SYSTEM_PROMPT}\n\n"
            "## 当前执行上下文\n"
            f"- 当前 Lane: {lane}\n"
            f"- 当前工作目录: {workspace}\n"
            f"- 用户主仓库目录: {self.config.workspace.resolve()}\n\n"
            "本次任务必须在当前 Lane 的工作目录中执行。所有相对路径都相对于"
            "当前工作目录；不要把用户主仓库目录当成当前工作目录，也不要跨 Lane"
            "读取或修改文件。需要执行 Git 操作时，也必须在当前 Lane 工作目录中执行。"
        )
        return Agent(
            session_id=self.session_id,
            llm_client=self.llm_client,
            tool_registry=registry,
            permission_manager=self.permission_manager,
            provider=provider,
            workspace=workspace,
            system_prompt=system_prompt,
            max_iterations=self.config.max_iterations,
            emit=self.emit,
        )

    async def run(self, user_message: str, lane: Optional[str] = None) -> RunResult:
        """执行一次 run。同一 session 内串行——不允许并发。"""
        if self._run_lock.locked():
            raise SessionBusyError("当前会话已有任务在执行，请等待完成")

        async with self._run_lock:
            target_lane = lane or self.lane_manager.current_lane
            if target_lane != self.lane_manager.current_lane:
                self.switch_lane(target_lane, allow_during_run=True)
            else:
                self.permission_manager.set_workspace(
                    self.workspace_for_lane(target_lane)
                )

            self.log.info("run_started", lane=target_lane, user_message=user_message[:200])
            agent = self.build_agent(target_lane)
            current_task = asyncio.current_task()
            self._active_run_task = current_task
            self._interrupt_requested = False
            try:
                result = await agent.run(user_message)
            finally:
                if self._active_run_task is current_task:
                    self._active_run_task = None
                    self._active_run_id = None
                    self._interrupt_requested = False
            if result.status == "completed" and self.git_manager.enabled:
                await self._handle_completed_run_checkpoint(target_lane, result)
            self.log.info(
                "run_completed",
                run_id=result.run_id,
                status=result.status,
                iterations=result.iterations,
                total_tokens=result.total_tokens,
                duration=result.duration,
            )
            return result

    async def _handle_completed_run_checkpoint(
        self, lane: str, result: RunResult
    ) -> None:
        mode = self.config.checkpoint_frequency_mode
        if mode not in {"safe", "balanced", "manual"}:
            mode = "balanced"
        entry_id = self.lane_manager.get_lane(lane).leaf_id
        try:
            if mode == "balanced":
                pending = self.git_manager.defer_run_checkpoint(
                    lane,
                    run_id=result.run_id,
                    conversation_entry_id=entry_id,
                )
                if pending["should_flush"]:
                    checkpoint = self.git_manager.checkpoint(
                        lane,
                        reason="run_completed_batch",
                        conversation_entry_id=entry_id,
                        run_id=result.run_id,
                        run_status=result.status,
                    )
                    self._cancel_checkpoint_flush(lane)
                    await self._emit_checkpoint_created(lane, checkpoint)
                else:
                    self._schedule_checkpoint_flush(lane)
                    await self.emit(
                        "lane_sync_state_changed",
                        {
                            "lane": lane,
                            "sync_state": "dirty",
                            "pending_checkpoint": True,
                            "pending_run_count": pending["pending_run_count"],
                            "changed_files": pending["changed_files"],
                            "next_flush_at": pending["next_flush_at"],
                            "message": "代码修改已暂存，连续任务将在检查点窗口结束后合并保存",
                        },
                    )
                return

            if mode == "manual":
                pending = self.git_manager.defer_run_checkpoint(
                    lane,
                    run_id=result.run_id,
                    conversation_entry_id=entry_id,
                )
                await self.emit(
                    "lane_sync_state_changed",
                    {
                        "lane": lane,
                        "sync_state": "dirty",
                        "pending_checkpoint": pending["pending"],
                        "pending_run_count": pending["pending_run_count"],
                        "changed_files": pending["changed_files"],
                        "message": "代码修改尚未提交，请手动创建检查点",
                    },
                )
                return

            checkpoint = self.git_manager.checkpoint(
                lane,
                reason="run_completed",
                conversation_entry_id=entry_id,
                run_id=result.run_id,
                run_status=result.status,
            )
            await self._emit_checkpoint_created(lane, checkpoint)
        except Exception as exc:  # checkpoint failure must preserve the run result
            logger.warning("automatic checkpoint failed: %s", exc)
            await self.emit(
                "lane_sync_state_changed",
                {
                    "lane": lane,
                    "sync_state": "dirty",
                    "pending_checkpoint": True,
                    "message": str(exc),
                },
            )

    async def _emit_checkpoint_created(self, lane: str, checkpoint) -> None:
        if checkpoint is None:
            return
        await self.emit(
            "lane_checkpoint_created",
            {
                "lane": lane,
                "checkpoint_id": checkpoint.checkpoint_id,
                "commit_sha": checkpoint.commit_sha,
                "short_head": checkpoint.commit_sha[:8],
                "changed_files": checkpoint.changed_files,
                "run_ids": checkpoint.run_ids,
            },
        )

    def _schedule_checkpoint_flush(self, lane: str) -> None:
        previous = self._checkpoint_flush_tasks.get(lane)
        if previous is not None and not previous.done():
            previous.cancel()
        self._checkpoint_flush_tasks[lane] = asyncio.create_task(
            self._flush_checkpoint_after_idle(lane)
        )

    async def _flush_checkpoint_after_idle(self, lane: str) -> None:
        task = asyncio.current_task()
        try:
            await asyncio.sleep(self.git_manager.checkpoint_merge_window_seconds)
            while self.is_running:
                await asyncio.sleep(0.25)
            pending = self.git_manager.pending_checkpoint_status(lane)
            if not pending["should_flush"]:
                return
            entry_id = self.lane_manager.get_lane(lane).leaf_id
            checkpoint = self.git_manager.checkpoint(
                lane,
                reason="run_completed_batch",
                conversation_entry_id=entry_id,
            )
            await self._emit_checkpoint_created(lane, checkpoint)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # background flush must not terminate the session
            logger.warning("delayed checkpoint flush failed: %s", exc)
            await self.emit(
                "lane_sync_state_changed",
                {
                    "lane": lane,
                    "sync_state": "dirty",
                    "pending_checkpoint": True,
                    "message": str(exc),
                },
            )
        finally:
            if task is not None and self._checkpoint_flush_tasks.get(lane) is task:
                self._checkpoint_flush_tasks.pop(lane, None)

    def cancel_checkpoint_flushes(self) -> None:
        for task in self._checkpoint_flush_tasks.values():
            if not task.done():
                task.cancel()
        self._checkpoint_flush_tasks.clear()

    # --- Lane + Git coordination ------------------------------------------

    def _ensure_no_active_run(self, operation: str) -> None:
        if self.is_running:
            raise AgentError(
                message=f"Agent 正在运行，暂时不能{operation}",
                code="SESSION_BUSY",
                suggestions=["等待当前运行完成，或先中断当前运行"],
            )

    def workspace_for_lane(self, lane: str) -> Path:
        return self.git_manager.active_workspace(lane)

    def lane_payload(self, lane: str) -> dict:
        pointer = self.lane_manager.get_lane(lane)
        payload = pointer.to_api_dict()
        payload["git"] = self.git_manager.lane_api(lane)
        return payload

    def list_lane_payloads(self, include_archived: bool = False) -> list[dict]:
        lanes = (
            self.lane_manager.list_lanes()
            if include_archived
            else self.lane_manager.list_active_lanes()
        )
        return [self.lane_payload(item.lane) for item in lanes]

    def create_lane(
        self, name: str, from_id: Optional[str], description: str = ""
    ) -> dict:
        self._ensure_no_active_run("创建 Lane")
        self.lane_manager.validate_new_lane(name)
        source_lane = self.lane_manager.current_lane
        source_pointer = self.lane_manager.get_lane(source_lane)
        if self.git_manager.enabled and from_id != source_pointer.leaf_id:
            raise AgentError(
                message="Git-backed Lane must branch from the current conversation head",
                code="LANE_CODE_BASELINE_MISMATCH",
                details={
                    "requested_entry_id": from_id,
                    "current_entry_id": source_pointer.leaf_id,
                },
                suggestions=["Switch to the desired Lane/head before creating the branch"],
            )
        git_created = False
        if self.git_manager.enabled:
            self.git_manager.create_lane(name, source_lane)
            self._cancel_checkpoint_flush(source_lane)
            git_created = True
        try:
            pointer = self.lane_manager.create_lane(
                name=name, from_id=from_id, description=description
            )
            self.lane_manager.switch_lane(name)
            self.permission_manager.set_workspace(self.workspace_for_lane(name))
            self.git_manager.complete_operation(self.git_manager.last_operation_id)
        except Exception:
            if git_created:
                self.git_manager.rollback_lane_creation(name)
            raise
        return self.lane_payload(pointer.lane)

    def switch_lane(self, lane: str, *, allow_during_run: bool = False) -> dict:
        if not allow_during_run:
            self._ensure_no_active_run("切换 Lane")
        current = self.lane_manager.current_lane
        self.lane_manager.get_lane(lane)
        if self.git_manager.enabled:
            self.git_manager.ensure_lane_ready(lane)
        if lane != current and self.git_manager.enabled:
            self.git_manager.checkpoint(current, reason="before_switch")
            self._cancel_checkpoint_flush(current)
        pointer = self.lane_manager.switch_lane(lane)
        self.permission_manager.set_workspace(self.workspace_for_lane(lane))
        return self.lane_payload(pointer.lane)

    def delete_lane(self, lane: str) -> None:
        self._ensure_no_active_run("删除 Lane")
        if lane == "main" or lane == self.lane_manager.current_lane:
            self.lane_manager.delete_lane(lane)
            return
        self.lane_manager.get_lane(lane)
        if self.git_manager.enabled:
            self.git_manager.remove_lane(lane)
            self._cancel_checkpoint_flush(lane)
        self.lane_manager.delete_lane(lane)

    def checkpoint_lane(
        self,
        lane: str,
        reason: str = "manual",
        paths: Optional[list[str]] = None,
        allow_blocked: bool = False,
    ) -> dict:
        self._ensure_no_active_run("创建代码检查点")
        checkpoint = self.git_manager.checkpoint(
            lane,
            reason=reason,
            conversation_entry_id=self.lane_manager.get_lane(lane).leaf_id,
            include_paths=paths,
            allow_blocked=allow_blocked,
        )
        if checkpoint is not None:
            pending_task = self._checkpoint_flush_tasks.pop(lane, None)
            if pending_task is not None and not pending_task.done():
                pending_task.cancel()
        return {
            "created": checkpoint is not None,
            "checkpoint": checkpoint.to_dict() if checkpoint else None,
            "lane": self.lane_payload(lane),
        }

    def lane_status(self, lane: str) -> dict:
        self.lane_manager.get_lane(lane)
        return {"lane": lane, "git": self.git_manager.lane_api(lane)}

    def checkpoints(self, lane: str) -> list[dict]:
        self.lane_manager.get_lane(lane)
        return self.git_manager.list_checkpoints(lane)

    def restore_checkpoint(
        self, lane: str, checkpoint_id: str, discard_changes: bool = False
    ) -> dict:
        self._ensure_no_active_run("恢复代码检查点")
        self.lane_manager.get_lane(lane)
        result = self.git_manager.restore_checkpoint(
            lane, checkpoint_id, discard_changes=discard_changes
        )
        self._cancel_checkpoint_flush(lane)
        return result

    def discard_changes(self, lane: str) -> dict:
        self._ensure_no_active_run("丢弃代码修改")
        self.lane_manager.get_lane(lane)
        result = self.git_manager.discard_changes(lane)
        self._cancel_checkpoint_flush(lane)
        return result

    def _cancel_checkpoint_flush(self, lane: str) -> None:
        task = self._checkpoint_flush_tasks.pop(lane, None)
        if task is not None and not task.done():
            task.cancel()

    def publish_lane(
        self,
        lane: str,
        target_branch: str,
        mode: str = "branch",
        base_branch: Optional[str] = None,
    ) -> dict:
        self._ensure_no_active_run("发布 Lane")
        self.lane_manager.get_lane(lane)
        result = self.git_manager.publish(
            lane, target_branch, mode=mode, base_branch=base_branch
        )
        self._cancel_checkpoint_flush(lane)
        return result

    def archive_lane(self, lane: str) -> dict:
        self._ensure_no_active_run("归档 Lane")
        pointer = self.lane_manager.get_lane(lane)
        if self.git_manager.enabled and not pointer.archived:
            self.git_manager.checkpoint(lane, reason="before_archive")
        self._cancel_checkpoint_flush(lane)
        pointer = self.lane_manager.archive_lane(lane)
        return self.lane_payload(pointer.lane)

    def restore_lane(self, lane: str) -> dict:
        self._ensure_no_active_run("恢复 Lane")
        pointer = self.lane_manager.restore_lane(lane)
        if self.git_manager.enabled:
            self.git_manager.get_binding(lane)
        self._cancel_checkpoint_flush(lane)
        return self.lane_payload(pointer.lane)

    def compare_lanes(self, lane_a: str, lane_b: str) -> dict:
        comparison = self.lane_manager.compare_lanes(
            lane_a, lane_b, self.storage
        )
        comparison["code"] = self.git_manager.compare(lane_a, lane_b)
        return comparison

    # --- 查询 ---------------------------------------------------------------

    def snapshot(self) -> dict:
        """一次性返回前端渲染树所需的全部数据。"""
        lanes = self.lane_manager.list_active_lanes()
        return {
            "session_id": self.session_id,
            "workspace": str(self.workspace_for_lane(self.lane_manager.current_lane)),
            "source_workspace": str(self.config.workspace),
            "git_enabled": self.git_manager.enabled,
            "git_disabled_reason": self.git_manager.disabled_reason,
            "repository_root": str(self.git_manager.repository_root)
            if self.git_manager.repository_root
            else None,
            "pending_git_operations": self.git_manager.store.pending_operations(),
            "current_lane": self.lane_manager.current_lane,
            "agent_state": self.state.value,
            "is_running": self.is_running,
            "command_allowlist": self.permission_manager.get_command_allowlist(),
            "lanes": [self.lane_payload(lane.lane) for lane in lanes],
            "entries": [entry.to_api_dict() for entry in self.storage.all_entries()],
        }


class SessionManager:
    """进程内的 session 注册表。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._sessions: dict[str, SessionRuntime] = {}

    def create(
        self, session_id: Optional[str] = None, workspace: Optional[str] = None
    ) -> SessionRuntime:
        sid = session_id or uuid.uuid4().hex[:12]
        if sid in self._sessions:
            return self._sessions[sid]
        runtime_config = self._config_for_session(sid, workspace)
        self._write_meta(
            sid, runtime_config.workspace, runtime_config.command_allowlist
        )
        runtime = SessionRuntime(sid, runtime_config)
        self._sessions[sid] = runtime
        return runtime

    def get(self, session_id: str) -> Optional[SessionRuntime]:
        return self._sessions.get(session_id)

    def get_or_load(self, session_id: str) -> Optional[SessionRuntime]:
        """已在内存则直接返回，否则尝试从磁盘恢复。"""
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        data_dir = Path(self.config.data_dir)
        path = data_dir / f"{session_id}.jsonl"
        lanes_path = data_dir / f"{session_id}_lanes.jsonl"
        meta_path = self._meta_path(session_id)
        if not path.exists() and not lanes_path.exists() and not meta_path.exists():
            return None
        return self.create(session_id)

    def list_sessions(self) -> list[dict]:
        """列出磁盘上的所有 session。"""
        data_dir = Path(self.config.data_dir)
        if not data_dir.exists():
            return []
        session_ids: set[str] = set()
        for path in data_dir.glob("*.jsonl"):
            if path.stem.endswith("_lanes"):
                continue
            session_ids.add(path.stem)
        for path in data_dir.glob("*_lanes.jsonl"):
            session_ids.add(path.stem.removesuffix("_lanes"))
        for path in data_dir.glob("*_meta.json"):
            session_ids.add(path.stem.removesuffix("_meta"))

        def updated_at(session_id: str) -> float:
            candidates = [
                data_dir / f"{session_id}.jsonl",
                data_dir / f"{session_id}_lanes.jsonl",
                self._meta_path(session_id),
            ]
            mtimes = [path.stat().st_mtime for path in candidates if path.exists()]
            return max(mtimes) if mtimes else 0.0

        result: list[dict] = []
        for session_id in sorted(session_ids, key=updated_at, reverse=True):
            result.append(
                {
                    "session_id": session_id,
                    "updated_at": updated_at(session_id),
                    "loaded": session_id in self._sessions,
                    "workspace": str(self._workspace_for_session(session_id)),
                }
            )
        return result

    def delete(self, session_id: str) -> None:
        """删除 session：从内存移除 + 删除磁盘文件。"""
        runtime = self._sessions.get(session_id)
        if runtime is not None:
            runtime.cancel_checkpoint_flushes()
            runtime.git_manager.close_worktrees()
            runtime.storage.delete_files()
            runtime.lane_manager.delete_files()
            runtime.git_manager.delete_files()
            self._sessions.pop(session_id, None)
        self._meta_path(session_id).unlink(missing_ok=True)

    def _config_for_session(
        self, session_id: str, workspace: Optional[str] = None
    ) -> AppConfig:
        meta = self._read_meta(session_id)
        raw_allowlist = meta.get("command_allowlist")
        return replace(
            self.config,
            workspace=self._resolve_workspace(workspace)
            if workspace
            else self._workspace_for_session(session_id),
            command_allowlist=(
                [str(item) for item in raw_allowlist if str(item).strip()]
                if isinstance(raw_allowlist, list)
                else list(self.config.command_allowlist)
            ),
        )

    @staticmethod
    def _resolve_workspace(workspace: str) -> Path:
        return Path(workspace).expanduser().resolve()

    def _workspace_for_session(self, session_id: str) -> Path:
        raw_workspace = self._read_meta(session_id).get("workspace")
        if isinstance(raw_workspace, str) and raw_workspace.strip():
            return self._resolve_workspace(raw_workspace)
        return self.config.workspace

    def _meta_path(self, session_id: str) -> Path:
        return Path(self.config.data_dir) / f"{session_id}_meta.json"

    def _read_meta(self, session_id: str) -> dict:
        path = self._meta_path(session_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("session %s 的 meta 文件读取失败，使用默认配置", session_id)
            return {}

    def _write_meta(
        self, session_id: str, workspace: Path, command_allowlist: list[str] | None = None
    ) -> None:
        path = self._meta_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "workspace": str(workspace),
            "command_allowlist": command_allowlist
            if command_allowlist is not None
            else list(self.config.command_allowlist),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def update_command_allowlist(
        self, session_id: str, commands: list[str]
    ) -> SessionRuntime:
        runtime = self.get_or_load(session_id)
        if runtime is None:
            raise KeyError(session_id)
        normalized = runtime.permission_manager.set_command_allowlist(commands)
        runtime.config = replace(runtime.config, command_allowlist=normalized)
        self._write_meta(session_id, runtime.config.workspace, normalized)
        return runtime
