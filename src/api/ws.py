"""WebSocket 端点：流式事件推送。

对应代码设计 02 号文档 2.2 节、03 号文档八节。

关键实现点：
1. 权限确认通过 Future 异步等待用户响应（session_service.py 里的实现）
2. 连接断开时必须清理挂起的权限请求，否则 run 会永久挂起
3. 所有推送事件用统一信封格式 {type, data}
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..errors.types import AgentError
from .schemas import PermissionResponseIn, SendMessageIn, WSEnvelope
from .session_service import SessionManager, SessionRuntime

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """单个 session 的 WebSocket 连接。

    一个连接的生命周期：
    1. accept 连接
    2. 从 app.state 取 SessionManager，get_or_load(session_id)
    3. 注入 emit 回调
    4. 循环接收消息并分发
    5. 断开时清理挂起的权限请求
    """
    await websocket.accept()
    logger.info("WebSocket 连接建立: session=%s", session_id)

    manager: SessionManager = websocket.app.state.session_manager
    runtime = manager.get_or_load(session_id)
    if runtime is None:
        await websocket.send_json(
            {
                "type": "error",
                "data": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"会话不存在: {session_id}",
                },
            }
        )
        await websocket.close()
        return

    # 注入事件推送回调
    runtime.set_emitter(lambda event, payload: _emit(websocket, event, payload))

    try:
        async for message in websocket.iter_json():
            await _handle_message(websocket, runtime, message)
    except WebSocketDisconnect:
        logger.info("WebSocket 连接断开: session=%s", session_id)
    except Exception:
        logger.exception("WebSocket 处理出现未预期错误")
    finally:
        runtime.set_emitter(None)
        runtime.fail_pending_permissions("连接已断开")


async def _handle_message(
    websocket: WebSocket, runtime: SessionRuntime, message: dict
):
    """分发客户端消息。"""
    msg_type = message.get("type")

    if msg_type == "send_message":
        await _handle_send_message(websocket, runtime, message)
    elif msg_type == "permission_response":
        _handle_permission_response(runtime, message)
    else:
        logger.warning("未知的消息类型: %s", msg_type)


async def _handle_send_message(
    websocket: WebSocket, runtime: SessionRuntime, message: dict
):
    """处理用户发送的新消息，触发 Agent.run()。"""
    try:
        data = SendMessageIn(**message)
    except Exception as exc:
        await _emit(
            websocket,
            "error",
            {"code": "INVALID_REQUEST", "message": f"消息格式错误: {exc}"},
        )
        return

    try:
        result = await runtime.run(data.content, lane=data.lane)
        await _emit(
            websocket,
            "run_completed",
            {
                "run_id": result.run_id,
                "status": result.status,
                "iterations": result.iterations,
                "total_tokens": result.total_tokens,
                "duration": result.duration,
            },
        )
    except AgentError as exc:
        await _emit(
            websocket,
            "run_error",
            {
                "code": exc.code,
                "message": exc.message,
                "suggestions": getattr(exc, "suggestions", []),
            },
        )
    except Exception as exc:
        logger.exception("run 执行出现未预期错误")
        await _emit(
            websocket,
            "run_error",
            {"code": "INTERNAL_ERROR", "message": f"内部错误: {exc}"},
        )


def _handle_permission_response(runtime: SessionRuntime, message: dict):
    """处理用户的权限确认响应。"""
    try:
        data = PermissionResponseIn(**message)
    except Exception as exc:
        logger.warning("权限响应格式错误: %s", exc)
        return

    matched = runtime.resolve_permission(data.request_id, data.action)
    if not matched:
        logger.warning("权限响应的 request_id 未命中任何等待中的请求: %s", data.request_id)


async def _emit(websocket: WebSocket, event: str, payload: dict[str, Any]):
    """推送事件给前端，统一包 WSEnvelope。"""
    envelope = WSEnvelope(type=event, data=payload)
    try:
        await websocket.send_json(envelope.model_dump())
    except Exception:
        logger.warning("推送事件 %s 失败", event, exc_info=True)


# 风险级别映射（代码设计 02 号文档 2.3 节）
_RISK_LEVEL_MAP = {
    "safe": "low",
    "write": "medium",
    "dangerous": "high",
}
