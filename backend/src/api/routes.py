"""REST 路由：Session / Lane / 权限审计。

对应代码设计 02 号文档第二节。

分工原则（02 号文档一节）：**流式过程走 WebSocket，CRUD 走 REST**。
所以这里没有任何"发消息给 Agent"的端点——那是 WS 的 `send_message`。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..errors.types import (
    CODE_LANE_NOT_FOUND,
    CODE_SESSION_NOT_FOUND,
    LaneNotFoundError,
    SessionNotFoundError,
)
from .schemas import CreateLaneIn, CreateSessionIn
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
        "workspace": str(runtime.config.workspace),
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


@router.get("/filesystem/roots")
def list_filesystem_roots() -> dict:
    roots: list[dict[str, str]] = []

    if os.name == "nt":
        for code in range(ord("A"), ord("Z") + 1):
            root = Path(f"{chr(code)}:/")
            if root.exists():
                roots.append({"name": f"{chr(code)}:", "path": str(root)})
    else:
        roots.append({"name": "/", "path": "/"})

    home = Path.home()
    if home.exists():
        home_path = str(home)
        if all(item["path"] != home_path for item in roots):
            roots.insert(0, {"name": "Home", "path": home_path})

    return {"roots": roots}


@router.get("/filesystem/children")
def list_directory_children(path: str = Query(...)) -> dict:
    if not path.strip():
        raise HTTPException(status_code=400, detail="path is required")

    directory = Path(path).expanduser()
    try:
        resolved = directory.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="path is not a directory")

    children: list[dict[str, str]] = []
    try:
        candidates = sorted(resolved.iterdir(), key=lambda item: item.name.lower())
        for child in candidates:
            try:
                if child.is_dir():
                    children.append({"name": child.name, "path": str(child)})
            except OSError:
                continue
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parent = resolved.parent if resolved.parent != resolved else None
    return {
        "path": str(resolved),
        "parent": str(parent) if parent else None,
        "children": children[:300],
    }


# --- Lane ------------------------------------------------------------------


@router.get("/sessions/{session_id}/lanes")
def list_lanes(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    runtime = _require_session(manager, session_id)
    return {
        "current_lane": runtime.lane_manager.current_lane,
        "lanes": [lane.to_api_dict() for lane in runtime.lane_manager.list_lanes()],
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
    pointer = runtime.lane_manager.create_lane(
        name=body.name, from_id=from_id, description=body.description
    )
    await runtime.emit("lane_created", {"lane": pointer.lane, "from_id": pointer.created_from})
    return pointer.to_api_dict()


@router.post("/sessions/{session_id}/lanes/{lane}/switch")
async def switch_lane(
    session_id: str, lane: str, manager: SessionManager = Depends(get_manager)
) -> dict:
    runtime = _require_session(manager, session_id)
    pointer = runtime.lane_manager.switch_lane(lane)
    await runtime.emit("lane_switched", {"lane": pointer.lane, "leaf_id": pointer.leaf_id})
    return pointer.to_api_dict()


@router.delete("/sessions/{session_id}/lanes/{lane}", status_code=204, response_model=None)
async def delete_lane(
    session_id: str, lane: str, manager: SessionManager = Depends(get_manager)
) -> None:
    """删除分支指针，不删树中的节点。保护 main 和当前活跃分支。"""
    runtime = _require_session(manager, session_id)
    runtime.lane_manager.delete_lane(lane)
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
    return runtime.lane_manager.compare_lanes(a, b, runtime.storage)


# --- 权限审计 --------------------------------------------------------------


@router.get("/sessions/{session_id}/permissions/audit")
def permission_audit(
    session_id: str, manager: SessionManager = Depends(get_manager)
) -> dict:
    runtime = _require_session(manager, session_id)
    return runtime.permission_manager.audit_report()
