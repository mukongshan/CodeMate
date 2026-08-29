"""REST 路由：Session / Lane / 权限审计。

对应代码设计 02 号文档第二节。

分工原则（02 号文档一节）：**流式过程走 WebSocket，CRUD 走 REST**。
所以这里没有任何"发消息给 Agent"的端点——那是 WS 的 `send_message`。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

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
    runtime = manager.create(body.session_id if body else None)
    return {"session_id": runtime.session_id, "current_lane": runtime.lane_manager.current_lane}


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


# --- Lane ------------------------------------------------------------------


@router.get("/sessions/{session_id}/lanes")
def list_lanes(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    runtime = _require_session(manager, session_id)
    return {
        "current_lane": runtime.lane_manager.current_lane,
        "lanes": [lane.to_api_dict() for lane in runtime.lane_manager.list_lanes()],
    }


@router.post("/sessions/{session_id}/lanes", status_code=201)
def create_lane(
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
    return pointer.to_api_dict()


@router.post("/sessions/{session_id}/lanes/{lane}/switch")
def switch_lane(
    session_id: str, lane: str, manager: SessionManager = Depends(get_manager)
) -> dict:
    runtime = _require_session(manager, session_id)
    pointer = runtime.lane_manager.switch_lane(lane)
    return pointer.to_api_dict()


@router.delete("/sessions/{session_id}/lanes/{lane}", status_code=204, response_model=None)
def delete_lane(
    session_id: str, lane: str, manager: SessionManager = Depends(get_manager)
) -> None:
    """删除分支指针，不删树中的节点。保护 main 和当前活跃分支。"""
    runtime = _require_session(manager, session_id)
    runtime.lane_manager.delete_lane(lane)


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
