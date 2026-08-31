"""REST 路由：Session / Lane / 权限审计。

对应代码设计 02 号文档第二节。

分工原则（02 号文档一节）：**流式过程走 WebSocket，CRUD 走 REST**。
所以这里没有任何"发消息给 Agent"的端点——那是 WS 的 `send_message`。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..errors.types import (
    CODE_LANE_NOT_FOUND,
    CODE_SESSION_NOT_FOUND,
    LaneNotFoundError,
    SessionNotFoundError,
)
from .schemas import CreateLaneIn, CreateSessionIn, UpdatePermissionGateIn
from .session_service import SessionManager, SessionRuntime

router = APIRouter(prefix="/api")


def get_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


def _require_session(manager: SessionManager, session_id: str) -> SessionRuntime:
    runtime = manager.get_or_load(session_id)
    if runtime is None:
        raise SessionNotFoundError(
            message=f"会话不存在: {session_id}",
            code=CODE_SESSION_NOT_FOUND,
            session_id=session_id,
            suggestions=["使用 GET /api/sessions 查看已有会话"],
        )
    return runtime


# --- Session ---------------------------------------------------------------


@router.post("/sessions", status_code=201)
def create_session(
    body: CreateSessionIn | None = None,
    manager: SessionManager = Depends(get_manager),
) -> dict:
    runtime = manager.create(
        session_id=body.session_id if body else None,
        workspace=body.workspace if body else None,
    )
    return {
        "session_id": runtime.session_id,
        "workspace": str(
            runtime.workspace_for_lane(runtime.lane_manager.current_lane)
        ),
        "source_workspace": str(runtime.config.workspace),
        "git_enabled": runtime.git_manager.enabled,
        "current_lane": runtime.lane_manager.current_lane,
    }


@router.get("/sessions")
def list_sessions(manager: SessionManager = Depends(get_manager)) -> dict:
    return {"sessions": manager.list_sessions()}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    """返回全部 Entry，供前端首次加载渲染整棵树。"""
    return _require_session(manager, session_id).snapshot()


@router.delete("/sessions/{session_id}", status_code=204, response_model=None)
def delete_session(session_id: str, manager: SessionManager = Depends(get_manager)) -> None:
    _require_session(manager, session_id)
    manager.delete(session_id)


# --- Filesystem ------------------------------------------------------------


@router.post("/filesystem/pick-directory")
def pick_directory(initial_path: str | None = Query(default=None)) -> dict:
    selected = _pick_directory_with_windows_dialog(initial_path)
    return {"path": str(selected) if selected else None}


def _pick_directory_with_windows_dialog(initial_path: str | None = None) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Python tkinter is required to open the native directory picker",
        ) from exc

    initial_dir = _dialog_initial_dir(initial_path)
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    try:
        selected = filedialog.askdirectory(
            parent=root,
            title="选择工作区目录",
            initialdir=str(initial_dir),
            mustexist=True,
        )
    except tk.TclError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to open native directory picker: {exc}",
        ) from exc
    finally:
        root.destroy()

    if not selected:
        return None
    return Path(selected).resolve()


def _dialog_initial_dir(initial_path: str | None) -> Path:
    if initial_path:
        candidate = Path(initial_path).expanduser()
        if candidate.exists():
            return candidate if candidate.is_dir() else candidate.parent
    return Path.home()


# --- Lane ------------------------------------------------------------------


@router.get("/sessions/{session_id}/lanes")
def list_lanes(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    runtime = _require_session(manager, session_id)
    return {
        "current_lane": runtime.lane_manager.current_lane,
        "lanes": runtime.list_lane_payloads(),
    }


@router.post("/sessions/{session_id}/lanes", status_code=201)
async def create_lane(
    session_id: str,
    body: CreateLaneIn,
    manager: SessionManager = Depends(get_manager),
) -> dict:
    runtime = _require_session(manager, session_id)
    from_id = body.from_id
    if from_id is None:
        from_id = runtime.lane_manager.get_lane(runtime.lane_manager.current_lane).leaf_id
    payload = runtime.create_lane(
        name=body.name,
        from_id=from_id,
        description=body.description or "",
    )
    await runtime.emit(
        "lane_created",
        {
            "lane": payload["lane"],
            "from_id": payload["created_from"],
            "workspace": payload["git"].get("workspace"),
        },
    )
    await runtime.emit(
        "lane_switched",
        {
            "lane": payload["lane"],
            "leaf_id": payload["leaf_id"],
            "workspace": payload["git"].get("workspace"),
        },
    )
    return payload


@router.post("/sessions/{session_id}/lanes/{lane}/switch")
async def switch_lane(
    session_id: str, lane: str, manager: SessionManager = Depends(get_manager)
) -> dict:
    runtime = _require_session(manager, session_id)
    payload = runtime.switch_lane(lane)
    await runtime.emit(
        "lane_switched",
        {
            "lane": payload["lane"],
            "leaf_id": payload["leaf_id"],
            "workspace": payload["git"].get("workspace"),
        },
    )
    return payload


@router.delete("/sessions/{session_id}/lanes/{lane}", status_code=204, response_model=None)
async def delete_lane(
    session_id: str, lane: str, manager: SessionManager = Depends(get_manager)
) -> None:
    """删除分支指针，不删树中的节点。保护 main 和当前活跃分支。"""
    runtime = _require_session(manager, session_id)
    runtime.delete_lane(lane)
    await runtime.emit("lane_deleted", {"lane": lane})


@router.get("/sessions/{session_id}/lanes/compare")
def compare_lanes(
    session_id: str,
    a: str = Query(..., description="分支 A"),
    b: str = Query(..., description="分支 B"),
    manager: SessionManager = Depends(get_manager),
) -> dict:
    runtime = _require_session(manager, session_id)
    for name in (a, b):
        if not runtime.lane_manager.has_lane(name):
            raise LaneNotFoundError(
                message=f"分支不存在: {name}",
                code=CODE_LANE_NOT_FOUND,
                lane=name,
                suggestions=["使用 GET /api/sessions/{id}/lanes 查看当前所有分支"],
            )
    return runtime.compare_lanes(a, b)


@router.get("/sessions/{session_id}/lanes/compare/file")
def compare_lane_file(
    session_id: str,
    a: str = Query(..., description="Lane A"),
    b: str = Query(..., description="Lane B"),
    path: str = Query(..., description="Repository-relative file path"),
    manager: SessionManager = Depends(get_manager),
) -> dict:
    runtime = _require_session(manager, session_id)
    for name in (a, b):
        if not runtime.lane_manager.has_lane(name):
            raise LaneNotFoundError(
                message=f"Lane not found: {name}",
                code=CODE_LANE_NOT_FOUND,
                lane=name,
            )
    return runtime.git_manager.file_diff(a, b, path)


@router.post("/sessions/{session_id}/lanes/{lane}/checkpoint")
async def create_lane_checkpoint(
    session_id: str,
    lane: str,
    manager: SessionManager = Depends(get_manager),
) -> dict:
    runtime = _require_session(manager, session_id)
    payload = runtime.checkpoint_lane(lane)
    checkpoint = payload.get("checkpoint")
    if checkpoint:
        await runtime.emit(
            "lane_checkpoint_created",
            {
                "lane": lane,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "commit_sha": checkpoint["commit_sha"],
                "short_head": checkpoint["commit_sha"][:8],
                "changed_files": checkpoint["changed_files"],
            },
        )
    return payload


# --- 权限审计 --------------------------------------------------------------


@router.get("/sessions/{session_id}/permissions/audit")
def permission_audit(
    session_id: str, manager: SessionManager = Depends(get_manager)
) -> dict:
    runtime = _require_session(manager, session_id)
    return runtime.permission_manager.audit_report()


@router.get("/sessions/{session_id}/permissions/gate")
def permission_gate(
    session_id: str, manager: SessionManager = Depends(get_manager)
) -> dict:
    runtime = _require_session(manager, session_id)
    return {
        "command_allowlist": runtime.permission_manager.get_command_allowlist()
    }


@router.put("/sessions/{session_id}/permissions/gate")
def update_permission_gate(
    session_id: str,
    body: UpdatePermissionGateIn,
    manager: SessionManager = Depends(get_manager),
) -> dict:
    runtime = _require_session(manager, session_id)
    runtime = manager.update_command_allowlist(
        session_id, body.command_allowlist
    )
    return {
        "command_allowlist": runtime.permission_manager.get_command_allowlist()
    }
