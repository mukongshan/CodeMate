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
from ..agent.providers import TreeMessageProvider
from ..agent.state import AgentState, RunResult
from ..config import AppConfig
from ..llm.client import LLMClient
from ..observability.logger import StructuredLogger
from ..permission.manager import PermissionManager, normalize_risk_level
from ..storage.lane_manager import LaneManager
from ..storage.session_storage import SessionStorage
from ..tools.registry import ToolRegistry
from ..tools.subagent_tool import DelegateTaskTool

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
        self.log = StructuredLogger(session_id, config.log_dir)
        self.permission_manager = PermissionManager(
            workspace=config.workspace,
            config={"command_allowlist": config.command_allowlist},
        )
        self.llm_client: LLMClient = LLMClient.from_config(config.llm.to_client_dict())
        self._run_lock = asyncio.Lock()
        self._emit: Optional[EmitFn] = None
        self._emitter_token: Optional[str] = None
        self._pending_permissions: dict[str, asyncio.Future] = {}
        self.state = AgentState.IDLE

        self.log.info(
            "agent_started",
            workspace=str(config.workspace),
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

    def build_agent(self, lane: str) -> Agent:
        registry = ToolRegistry.default(self.config.workspace)
        registry.register(
            DelegateTaskTool(
                session_id=self.session_id,
                workspace=self.config.workspace,
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
        return Agent(
            session_id=self.session_id,
            llm_client=self.llm_client,
            tool_registry=registry,
            permission_manager=self.permission_manager,
            provider=provider,
            workspace=self.config.workspace,
            max_iterations=self.config.max_iterations,
            emit=self.emit,
        )

    async def run(self, user_message: str, lane: Optional[str] = None) -> RunResult:
        """执行一次 run。同一 session 内串行——不允许并发。"""
        if self._run_lock.locked():
            raise SessionBusyError("当前会话已有任务在执行，请等待完成")

        async with self._run_lock:
            target_lane = lane or self.lane_manager.current_lane
            self.lane_manager.switch_lane(target_lane)

            self.log.info("run_started", lane=target_lane, user_message=user_message[:200])
            agent = self.build_agent(target_lane)
            result = await agent.run(user_message)
            self.log.info(
                "run_completed",
                run_id=result.run_id,
                status=result.status,
                iterations=result.iterations,
                total_tokens=result.total_tokens,
                duration=result.duration,
            )
            return result

    # --- 查询 ---------------------------------------------------------------

    def snapshot(self) -> dict:
        """一次性返回前端渲染树所需的全部数据。"""
        lanes = self.lane_manager.list_lanes()
        return {
            "session_id": self.session_id,
            "workspace": str(self.config.workspace),
            "current_lane": self.lane_manager.current_lane,
            "agent_state": self.state.value,
            "is_running": self.is_running,
            "command_allowlist": self.permission_manager.get_command_allowlist(),
            "lanes": [lane.to_api_dict() for lane in lanes],
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
        runtime = self._sessions.pop(session_id, None)
        if runtime is not None:
            runtime.storage.delete_files()
            runtime.lane_manager.delete_files()
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
