"""会话服务：把存储、LLM、工具、权限、Agent 装配成一个可用的会话。

对应代码设计 02 号文档、03 号文档九节。

一个 ``SessionRuntime`` 对应一个 session。执行模型上有一条硬约束
（03 号文档 7.3 节）：**任意时刻只有一个 Lane 在跑**，所以运行锁是
session 级的，不按 Lane 分。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException

from ..agent.loop import Agent
from ..agent.prompts import MAIN_SYSTEM_PROMPT
from ..agent.providers import TreeMessageProvider
from ..agent.state import AgentState, RunResult
from ..config import AppConfig
from ..errors.types import AgentError
from ..llm.client import LLMClient
from ..memory.manager import MemoryManager
from ..memory.project import load_project_context
from ..observability.logger import StructuredLogger
from ..permission.manager import PermissionManager, normalize_risk_level
from ..storage.lane_manager import LaneManager
from ..storage.session_storage import SessionStorage
from ..storage.workspace_storage import SessionPaths, WorkspaceRecord, WorkspaceStorage
from ..tools.registry import ToolRegistry
from ..tools.subagent_tool import DelegateTaskTool
from ..version_control import GitLaneManager

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, dict], Awaitable[None]]


class SessionBusyError(RuntimeError):
    """当前 session 已有 run 在执行。"""


class SessionRuntime:
    """单个会话的完整运行时。"""

    def __init__(
        self,
        session_id: str,
        config: AppConfig,
        *,
        paths: SessionPaths | None = None,
        workspace_id: str | None = None,
        title: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.config = config
        self.paths = paths
        self.workspace_id = workspace_id
        self.title = title or session_id
        self.storage = SessionStorage(
            session_id,
            config.data_dir,
            path=paths.entries if paths is not None else None,
        )
        self.lane_manager = LaneManager(
            session_id,
            config.data_dir,
            path=paths.lanes if paths is not None else None,
        )
        self.git_manager = GitLaneManager(
            session_id=session_id,
            source_workspace=config.workspace,
            data_dir=paths.git_dir if paths is not None else config.data_dir,
            worktree_root=config.worktree_root,
            max_file_bytes=config.checkpoint_max_file_bytes,
            checkpoint_merge_window_seconds=config.checkpoint_merge_window_seconds,
            checkpoint_max_pending_runs=config.checkpoint_max_pending_runs,
            checkpoint_max_pending_files=config.checkpoint_max_pending_files,
            checkpoint_max_pending_seconds=config.checkpoint_max_pending_seconds,
            session_layout=paths is not None,
        )
        if self.git_manager.enabled:
            for pointer in self.lane_manager.list_lanes():
                if not self.git_manager.has_binding(pointer.lane):
                    self.git_manager.ensure_legacy_lane(pointer.lane)
            self.git_manager.reconcile_operations(
                {pointer.lane for pointer in self.lane_manager.list_lanes()}
            )
        self.log = StructuredLogger(
            session_id, paths.logs_dir if paths is not None else config.log_dir
        )
        active_workspace = self.workspace_for_lane(self.lane_manager.current_lane)
        self.permission_manager = PermissionManager(
            workspace=active_workspace,
            config={"command_blacklist": config.command_blacklist},
        )
        self.llm_client: LLMClient = LLMClient.from_config(config.llm.to_client_dict())
        self.memory_manager = MemoryManager(
            self.storage,
            self.lane_manager,
            self.llm_client,
            active_workspace,
            max_context_tokens=config.max_context_tokens,
            reserve_tokens=config.context_reserve_tokens,
            keep_recent_tokens=config.compaction_keep_recent_tokens,
            summary_max_tokens=config.compaction_summary_max_tokens,
            threshold_ratio=config.compaction_threshold_ratio,
        )
        self._run_lock = asyncio.Lock()
        self._emit: Optional[EmitFn] = None
        self._emitter_token: Optional[str] = None
        self._pending_permissions: dict[str, asyncio.Future] = {}
        self._active_run_task: Optional[asyncio.Task] = None
        self._active_run_id: Optional[str] = None
        self._interrupt_requested = False
        self._checkpoint_flush_tasks: dict[str, asyncio.Task] = {}
        self._pending_file_reviews: dict[str, dict] = {}
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
        if event == "tool_call_end" and payload.get("status") == "success":
            self._capture_file_review(payload, event_lane)
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

    def _capture_file_review(self, payload: dict, lane: str) -> None:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            return
        file_change = metadata.get("file_change")
        if not isinstance(file_change, dict):
            return
        rollback = file_change.get("rollback")
        if not isinstance(rollback, dict):
            return
        call_id = str(payload.get("call_id") or "")
        path = str(file_change.get("path") or "")
        before_base64 = rollback.get("before_base64")
        after_revision = rollback.get("after_revision")
        if not call_id or not path or not isinstance(before_base64, str) or not isinstance(after_revision, str):
            return
        try:
            before = base64.b64decode(before_base64, validate=True)
        except (ValueError, TypeError):
            return
        self._pending_file_reviews[call_id] = {
            "review_id": call_id,
            "lane": lane,
            "path": path,
            "before": before,
            "before_exists": bool(rollback.get("before_exists", True)),
            "after_revision": after_revision,
        }
        sanitized_metadata = dict(metadata)
        sanitized_change = dict(file_change)
        sanitized_change.pop("rollback", None)
        sanitized_metadata["file_change"] = sanitized_change
        payload["metadata"] = sanitized_metadata

    def accept_file_review(self, review_id: str, lane: Optional[str] = None) -> dict:
        self._ensure_no_active_run('确认文件修改')
        review = self._pending_file_reviews.get(review_id)
        if review is None or (lane is not None and review["lane"] != lane):
            raise HTTPException(status_code=404, detail="文件审查记录不存在或不属于当前 Lane")
        self._pending_file_reviews.pop(review_id, None)
        return {"review_id": review_id, "accepted": True}

    def accept_file_reviews(self, lane: Optional[str] = None) -> dict:
        self._ensure_no_active_run('确认文件修改')
        review_ids = [
            review_id for review_id, review in self._pending_file_reviews.items()
            if lane is None or review["lane"] == lane
        ]
        for review_id in review_ids:
            self._pending_file_reviews.pop(review_id, None)
        return {"review_ids": review_ids, "accepted": True}

    def _file_review_workspace(self, review: dict) -> Path:
        return self.workspace_for_lane(review["lane"])

    def _validate_file_review_current(self, review: dict) -> None:
        path = self._file_review_workspace(review) / Path(review["path"])
        try:
            current = path.resolve(strict=True)
            current.relative_to(self._file_review_workspace(review).resolve())
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=409, detail="文件在审查期间已被删除或移出工作区")
        if ".git" in current.relative_to(self._file_review_workspace(review).resolve()).parts:
            raise HTTPException(status_code=403, detail="不允许回滚 Git 元数据")
        try:
            current_revision = hashlib.sha256(current.read_bytes()).hexdigest()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"读取待回滚文件失败: {exc}") from exc
        if current_revision != review["after_revision"]:
            raise HTTPException(status_code=409, detail="文件在审查期间已被再次修改，未执行回滚")

    def reject_file_review(self, review_id: str, lane: Optional[str] = None) -> dict:
        from .workspace_files import restore_file

        self._ensure_no_active_run('拒绝文件修改')
        review = self._pending_file_reviews.get(review_id)
        if review is None or (lane is not None and review["lane"] != lane):
            raise HTTPException(status_code=404, detail="文件审查记录不存在或不属于当前 Lane")
        self._validate_file_review_current(review)
        result = restore_file(
            self._file_review_workspace(review),
            review["path"],
            review["before"],
            review["before_exists"],
            review["after_revision"],
        )
        self._pending_file_reviews.pop(review_id, None)
        self._cancel_checkpoint_flush(review["lane"])
        return {"review_id": review_id, "rejected": True, "file": result}

    def reject_file_reviews(self, lane: Optional[str] = None) -> dict:
        from .workspace_files import restore_file

        self._ensure_no_active_run('拒绝文件修改')
        review_items = [
            (review_id, review) for review_id, review in self._pending_file_reviews.items()
            if lane is None or review["lane"] == lane
        ]
        latest_by_path: dict[tuple[str, str], dict] = {}
        for _, review in review_items:
            latest_by_path[(review["lane"], review["path"])] = review
        for review in latest_by_path.values():
            self._validate_file_review_current(review)
        results = []
        for review_id, review in reversed(review_items):
            results.append(
                restore_file(
                    self._file_review_workspace(review),
                    review["path"],
                    review["before"],
                    review["before_exists"],
                    review["after_revision"],
                )
            )
            self._pending_file_reviews.pop(review_id, None)
            self._cancel_checkpoint_flush(review["lane"])
        return {"review_ids": [review_id for review_id, _ in review_items], "rejected": True, "files": results}

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
        project_context = load_project_context(workspace)
        if project_context:
            system_prompt += "\n\n" + project_context
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
            memory_manager=self.memory_manager,
        )

    async def compact(self, lane: Optional[str] = None) -> dict:
        """手动压缩当前会话指定 Lane 的历史。"""
        if self._run_lock.locked():
            raise SessionBusyError("当前会话已有任务在执行，请等待完成")

        async with self._run_lock:
            target_lane = lane or self.lane_manager.current_lane
            self.lane_manager.get_lane(target_lane)
            self.permission_manager.set_workspace(self.workspace_for_lane(target_lane))
            result = await self.memory_manager.compact_if_needed(
                target_lane, reason="manual", force=True
            )
            result = result or {"status": "noop", "reason": "没有可压缩的历史"}
            result["lane"] = target_lane
            if result.get("status") in {"completed", "failed"}:
                event = "compaction_completed" if result["status"] == "completed" else "compaction_failed"
                await self.emit(event, result)
            return result

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
            for review_id, review in list(self._pending_file_reviews.items()):
                if review["lane"] == target_lane:
                    self._pending_file_reviews.pop(review_id, None)

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
                    if not pending.get("pending", False):
                        return
                    self._schedule_checkpoint_flush(lane)
                    await self.emit(
                        "lane_sync_state_changed",
                        {
                            "lane": lane,
                            "sync_state": "dirty",
                            "pending_checkpoint": True,
                            "pending_run_count": pending.get("pending_run_count", 0),
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
                if not pending.get("pending", False):
                    return
                await self.emit(
                    "lane_sync_state_changed",
                    {
                        "lane": lane,
                        "sync_state": "dirty",
                        "pending_checkpoint": pending["pending"],
                        "pending_run_count": pending.get("pending_run_count", 0),
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

    def rename_lane(self, lane: str, new_lane: str) -> dict:
        self._ensure_no_active_run("重命名 Lane")
        self.lane_manager.get_lane(lane)
        self.lane_manager.validate_new_lane(new_lane)
        self.git_manager.rename_lane(lane, new_lane)
        try:
            pointer = self.lane_manager.rename_lane(lane, new_lane)
        except Exception:
            self.git_manager.rename_lane(new_lane, lane)
            raise
        self._cancel_checkpoint_flush(lane)
        self.permission_manager.set_workspace(self.workspace_for_lane(new_lane))
        return self.lane_payload(pointer.lane)

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

    def git_status(self, lane: str) -> dict:
        self.lane_manager.get_lane(lane)
        return self.git_manager.git_status(lane)

    def git_diff(self, lane: str, path: str | None = None, staged: bool = False) -> dict:
        self.lane_manager.get_lane(lane)
        return self.git_manager.git_diff(lane, path=path, staged=staged)

    def git_stage(self, lane: str, paths: list[str]) -> dict:
        self._ensure_no_active_run("暂存 Git 文件")
        self.lane_manager.get_lane(lane)
        return self.git_manager.git_stage(lane, paths)

    def git_unstage(self, lane: str, paths: list[str]) -> dict:
        self._ensure_no_active_run("取消暂存 Git 文件")
        self.lane_manager.get_lane(lane)
        return self.git_manager.git_unstage(lane, paths)

    def git_commit(self, lane: str, message: str) -> dict:
        self._ensure_no_active_run("提交 Git 修改")
        self.lane_manager.get_lane(lane)
        return self.git_manager.git_commit(lane, message)

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

    def integration_preview(
        self, lane: str, target_branch: Optional[str] = None
    ) -> dict:
        self.lane_manager.get_lane(lane)
        return self.git_manager.integration_preview(lane, target_branch)

    def integrate_lane(
        self,
        lane: str,
        target_branch: Optional[str] = None,
        strategy: str = "merge",
    ) -> dict:
        self._ensure_no_active_run("集成 Lane 代码")
        self.lane_manager.get_lane(lane)
        main_entry_id = self.lane_manager.get_lane("main").leaf_id
        result = self.git_manager.integrate(
            lane,
            target_branch,
            strategy=strategy,
            conversation_entry_id=main_entry_id,
        )
        self._cancel_checkpoint_flush("main")
        return result

    def integrations(self) -> list[dict]:
        return self.git_manager.list_integrations()

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
        current_lane = self.lane_manager.current_lane
        memory = self.memory_manager.budget_status(current_lane)
        return {
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "workspace": str(self.workspace_for_lane(self.lane_manager.current_lane)),
            "source_workspace": str(self.config.workspace),
            "git_enabled": self.git_manager.enabled,
            "git_disabled_reason": self.git_manager.disabled_reason,
            "repository_root": str(self.git_manager.repository_root)
            if self.git_manager.repository_root
            else None,
            "pending_git_operations": self.git_manager.store.pending_operations(),
            "integrations": self.git_manager.list_integrations(),
            "current_lane": current_lane,
            "memory": memory,
            "agent_state": self.state.value,
            "is_running": self.is_running,
            "command_blacklist": self.permission_manager.get_command_blacklist(),
            "lanes": [self.lane_payload(lane.lane) for lane in lanes],
            "entries": [entry.to_api_dict() for entry in self.storage.all_entries()],
        }


class SessionManager:
    """进程内 Session 注册表与持久化 Workspace 管理入口。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._sessions: dict[str, SessionRuntime] = {}
        self.workspace_storage = WorkspaceStorage(config.data_dir)
        self._recover_deletion_journals()

    def legacy_migration_plan(self) -> list[dict]:
        return self.workspace_storage.legacy_migration_plan(self.config.workspace)

    def migrate_legacy_sessions(self) -> int:
        return self.workspace_storage.migrate_legacy_sessions(self.config.workspace)

    def create(
        self,
        session_id: Optional[str] = None,
        workspace: Optional[str] = None,
        workspace_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> SessionRuntime:
        sid = session_id or uuid.uuid4().hex[:12]
        if sid in self._sessions:
            return self._sessions[sid]
        existing_paths = self.workspace_storage.find_session(sid)
        if existing_paths is not None:
            loaded = self.get_or_load(sid)
            if loaded is not None:
                return loaded
        workspace_record = self._resolve_workspace_record(workspace, workspace_id)
        paths = self.workspace_storage.session_paths(workspace_record.workspace_id, sid)
        now = time.time()
        meta = {
            "session_id": sid,
            "workspace_id": workspace_record.workspace_id,
            "workspace": workspace_record.path,
            "workspace_title": workspace_record.title,
            "title": (title or sid).strip() or sid,
            "created_at": now,
            "updated_at": now,
            "command_blacklist": list(self.config.command_blacklist),
        }
        self.workspace_storage.write_session_meta(paths, meta)
        self.workspace_storage.attach_session(workspace_record.workspace_id, sid)
        try:
            runtime = self._build_runtime(paths, meta, workspace_record)
        except Exception:
            self.workspace_storage.detach_session(workspace_record.workspace_id, sid)
            self.workspace_storage.delete_session_directory(paths)
            raise
        self._sessions[sid] = runtime
        return runtime

    def get(self, session_id: str) -> Optional[SessionRuntime]:
        return self._sessions.get(session_id)

    def get_or_load(self, session_id: str) -> Optional[SessionRuntime]:
        """已在内存则直接返回，否则尝试从磁盘恢复。"""
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        paths = self.workspace_storage.find_session(session_id)
        if paths is None:
            return None
        meta = self.workspace_storage.read_session_meta(paths)
        workspace = self.workspace_storage.get_workspace(paths.workspace_id)
        if workspace is None:
            return None
        runtime = self._build_runtime(paths, meta, workspace)
        self._sessions[session_id] = runtime
        return runtime

    def list_sessions(self, workspace_id: Optional[str] = None) -> list[dict]:
        """按工作区注册表列出 Session，物理目录不再全局扫描。"""
        workspaces = (
            [self.workspace_storage.require_workspace(workspace_id)]
            if workspace_id is not None
            else self.workspace_storage.list_workspaces()
        )
        result: list[dict] = []
        for workspace in workspaces:
            for session_id in workspace.session_ids:
                paths = self.workspace_storage.session_paths(
                    workspace.workspace_id, session_id
                )
                meta = self.workspace_storage.read_session_meta(paths)
                if meta.get("workspace_id") != workspace.workspace_id:
                    continue
                result.append(self._session_summary(workspace, paths, meta))
        result.sort(key=lambda item: item["updated_at"], reverse=True)
        return result

    def delete(self, session_id: str) -> None:
        """删除 Session 目录以及所有非 main Lane 的托管 Git 资源。"""
        paths = self.workspace_storage.find_session(session_id)
        if paths is None:
            raise KeyError(session_id)
        operation_id = f"delete-session-{uuid.uuid4().hex}"
        journal = self.workspace_storage.write_deletion_journal(
            operation_id,
            {
                "operation_id": operation_id,
                "operation": "delete_session",
                "session_id": session_id,
                "workspace_id": paths.workspace_id,
                "state": "prepared",
                "updated_at": time.time(),
            },
        )
        runtime = self.get_or_load(session_id)
        git_cleaned = False
        try:
            if runtime is not None:
                runtime.cancel_checkpoint_flushes()
                runtime.git_manager.delete_managed_resources()
                self._sessions.pop(session_id, None)
            self.workspace_storage.write_deletion_journal(
                operation_id,
                {
                    "operation_id": operation_id,
                    "operation": "delete_session",
                    "session_id": session_id,
                    "workspace_id": paths.workspace_id,
                    "state": "git_cleaned",
                    "updated_at": time.time(),
                },
            )
            git_cleaned = True
            self.workspace_storage.detach_session(paths.workspace_id, session_id)
            self.workspace_storage.delete_session_directory(paths)
            journal.unlink(missing_ok=True)
        except Exception as exc:
            self.workspace_storage.write_deletion_journal(
                operation_id,
                {
                    "operation_id": operation_id,
                    "operation": "delete_session",
                    "session_id": session_id,
                    "workspace_id": paths.workspace_id,
                    "state": "failed",
                    "recoverable_from": "git_cleaned" if git_cleaned else None,
                    "error": str(exc),
                    "updated_at": time.time(),
                },
            )
            raise

    def list_workspaces(self) -> list[dict]:
        return [self._workspace_payload(item) for item in self.workspace_storage.list_workspaces()]

    def create_workspace(self, path: str, title: Optional[str] = None) -> tuple[dict, bool]:
        record, created = self.workspace_storage.create_workspace(path, title)
        return self._workspace_payload(record), created

    def rename_workspace(self, workspace_id: str, title: str) -> dict:
        return self._workspace_payload(
            self.workspace_storage.rename_workspace(workspace_id, title)
        )

    def delete_workspace(self, workspace_id: str, cascade: bool = False) -> None:
        workspace = self.workspace_storage.require_workspace(workspace_id)
        if workspace.session_ids and not cascade:
            raise ValueError("工作区仍包含会话，请确认级联删除")
        if cascade:
            for session_id in list(workspace.session_ids):
                self.delete(session_id)
        self.workspace_storage.remove_workspace(workspace_id)

    def rename_session(self, session_id: str, title: str) -> dict:
        paths = self.workspace_storage.find_session(session_id)
        if paths is None:
            raise KeyError(session_id)
        normalized = title.strip()
        if not normalized:
            raise ValueError("会话名称不能为空")
        meta = self.workspace_storage.read_session_meta(paths)
        meta["title"] = normalized
        meta["updated_at"] = time.time()
        self.workspace_storage.write_session_meta(paths, meta)
        runtime = self._sessions.get(session_id)
        if runtime is not None:
            runtime.title = normalized
        workspace = self.workspace_storage.require_workspace(paths.workspace_id)
        return self._session_summary(workspace, paths, meta)

    def _resolve_workspace_record(
        self, workspace: Optional[str], workspace_id: Optional[str]
    ) -> WorkspaceRecord:
        if workspace_id is not None:
            record = self.workspace_storage.require_workspace(workspace_id)
            if workspace is not None and Path(workspace).expanduser().resolve() != Path(record.path):
                raise ValueError("workspace_id 与 workspace 路径不一致")
            return record
        record, _ = self.workspace_storage.create_workspace(
            workspace or self.config.workspace
        )
        return record

    def _recover_deletion_journals(self) -> None:
        for journal, payload in self.workspace_storage.list_deletion_journals():
            if payload.get("operation") != "delete_session":
                continue
            recoverable = payload.get("state") == "git_cleaned" or (
                payload.get("state") == "failed"
                and payload.get("recoverable_from") == "git_cleaned"
            )
            if not recoverable:
                logger.warning("存在待人工重试的删除操作: %s", journal)
                continue
            workspace_id = str(payload.get("workspace_id") or "")
            session_id = str(payload.get("session_id") or "")
            if not workspace_id or not session_id:
                continue
            paths = self.workspace_storage.session_paths(workspace_id, session_id)
            workspace_record = self.workspace_storage.get_workspace(workspace_id)
            if workspace_record is not None:
                self.workspace_storage.detach_session(workspace_id, session_id)
            self.workspace_storage.delete_session_directory(paths)
            journal.unlink(missing_ok=True)

    def _build_runtime(
        self, paths: SessionPaths, meta: dict, workspace: WorkspaceRecord
    ) -> SessionRuntime:
        raw_blacklist = meta.get("command_blacklist")
        runtime_config = replace(
            self.config,
            workspace=Path(workspace.path),
            command_blacklist=(
                [str(item) for item in raw_blacklist if str(item).strip()]
                if isinstance(raw_blacklist, list)
                else list(self.config.command_blacklist)
            ),
        )
        return SessionRuntime(
            paths.session_id,
            runtime_config,
            paths=paths,
            workspace_id=workspace.workspace_id,
            title=str(meta.get("title") or paths.session_id),
        )

    def _workspace_payload(self, workspace: WorkspaceRecord) -> dict:
        return {
            **workspace.to_dict(),
            "session_count": len(workspace.session_ids),
            "status": "ok" if Path(workspace.path).is_dir() else "missing-dir",
        }

    def _session_summary(
        self, workspace: WorkspaceRecord, paths: SessionPaths, meta: dict
    ) -> dict:
        return {
            "session_id": paths.session_id,
            "workspace_id": workspace.workspace_id,
            "title": str(meta.get("title") or paths.session_id),
            "updated_at": max(
                float(meta.get("updated_at", 0.0)),
                self.workspace_storage.session_updated_at(paths),
            ),
            "created_at": float(meta.get("created_at", 0.0)),
            "loaded": paths.session_id in self._sessions,
            "workspace": workspace.path,
        }

    def update_command_blacklist(
        self, session_id: str, commands: list[str]
    ) -> SessionRuntime:
        runtime = self.get_or_load(session_id)
        if runtime is None:
            raise KeyError(session_id)
        normalized = runtime.permission_manager.set_command_blacklist(commands)
        runtime.config = replace(runtime.config, command_blacklist=normalized)
        if runtime.paths is not None:
            meta = self.workspace_storage.read_session_meta(runtime.paths)
            meta["command_blacklist"] = normalized
            meta["updated_at"] = time.time()
            self.workspace_storage.write_session_meta(runtime.paths, meta)
        return runtime
