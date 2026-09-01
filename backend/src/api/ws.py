from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..errors.types import AgentError
from .schemas import InterruptRunIn, PermissionResponseIn, SendMessageIn, WSEnvelope
from .session_service import SessionManager, SessionRuntime
from .terminal import TerminalSession, open_terminal, read_output

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info("WebSocket connected: session=%s", session_id)
    send_lock = asyncio.Lock()
    active_tasks: set[asyncio.Task[None]] = set()
    terminal_sessions: dict[str, TerminalSession] = {}

    manager: SessionManager = websocket.app.state.session_manager
    runtime = manager.get_or_load(session_id)
    if runtime is None:
        await websocket.send_json(
            {
                "type": "error",
                "data": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"session not found: {session_id}",
                },
            }
        )
        await websocket.close()
        return

    connection_id = uuid.uuid4().hex
    runtime.set_emitter(
        lambda event, payload: _emit(websocket, event, payload, send_lock),
        connection_id,
    )

    try:
        async for message in websocket.iter_json():
            task = await _handle_message(
                runtime,
                message,
                terminal_sessions,
                lambda event, payload: _emit(websocket, event, payload, send_lock),
            )
            if task is not None:
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    except RuntimeError as exc:
        if _is_closed_socket_error(exc):
            logger.info("WebSocket closed: session=%s", session_id)
        else:
            logger.exception("Unexpected WebSocket runtime error: session=%s", session_id)
    except Exception:
        logger.exception("Unexpected WebSocket handler error: session=%s", session_id)
    finally:
        for task in list(active_tasks):
            task.cancel("连接已断开")
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        for session in list(terminal_sessions.values()):
            await session.close()
        terminal_sessions.clear()
        if runtime.clear_emitter(connection_id):
            runtime.fail_pending_permissions("connection closed")


async def _handle_message(runtime: SessionRuntime, message: dict, terminal_sessions=None, emit=None):
    msg_type = message.get("type")

    if msg_type == "send_message":
        return asyncio.create_task(_handle_send_message(runtime, message))
    elif msg_type == "permission_response":
        _handle_permission_response(runtime, message)
    elif msg_type == "interrupt_run":
        await _handle_interrupt_run(runtime, message)
    elif msg_type == "terminal_open":
        return asyncio.create_task(_handle_terminal_open(runtime, message, terminal_sessions, emit))
    elif msg_type == "terminal_input":
        return asyncio.create_task(_handle_terminal_input(runtime, message, terminal_sessions, emit))
    elif msg_type == "terminal_resize":
        await _handle_terminal_resize(message, terminal_sessions, emit)
    elif msg_type == "terminal_signal":
        await _handle_terminal_signal(message, terminal_sessions, emit)
    elif msg_type == "terminal_close":
        await _handle_terminal_close(message, terminal_sessions, emit)
    else:
        logger.warning("Unknown websocket message type: %s", msg_type)
    return None


async def _handle_terminal_open(runtime, message, terminal_sessions, emit) -> None:
    if terminal_sessions is None or emit is None:
        return
    lane = runtime.lane_manager.current_lane
    requested_lane = message.get("lane")
    if requested_lane and requested_lane != lane:
        await emit("terminal_error", {"code": "TERMINAL_LANE_MISMATCH", "message": "终端只能打开当前 Lane 的工作目录", "lane": lane})
        return
    try:
        workspace = runtime.workspace_for_lane(lane)
        session = await open_terminal(workspace, lane)
        terminal_sessions[session.terminal_id] = session
        session.output_task = asyncio.create_task(read_output(session, emit))
        await emit("terminal_ready", {"terminal_id": session.terminal_id, "lane": lane, "workspace": str(workspace)})
    except Exception as exc:
        await emit("terminal_error", {"code": "TERMINAL_OPEN_FAILED", "message": str(exc), "lane": lane})


async def _handle_terminal_input(runtime, message, terminal_sessions, emit) -> None:
    if terminal_sessions is None or emit is None:
        return
    terminal_id = str(message.get("terminal_id") or "")
    session = terminal_sessions.get(terminal_id)
    if session is None:
        await emit("terminal_error", {"code": "TERMINAL_NOT_FOUND", "message": "终端会话不存在", "terminal_id": terminal_id})
        return
    text = str(message.get("text") or "")
    if not text:
        return
    decision = await runtime.permission_manager.check("bash", {"command": text})
    if not decision.allowed:
        await emit("terminal_error", {"code": "TERMINAL_PERMISSION_DENIED", "message": decision.reason, "terminal_id": terminal_id, "lane": session.lane})
        return
    try:
        await session.write(text)
    except Exception as exc:
        await emit("terminal_error", {"code": "TERMINAL_WRITE_FAILED", "message": str(exc), "terminal_id": terminal_id, "lane": session.lane})


async def _handle_terminal_resize(message, terminal_sessions, emit) -> None:
    terminal_id = str(message.get("terminal_id") or "")
    if terminal_sessions is None or emit is None or terminal_id not in terminal_sessions:
        return
    await emit("terminal_resized", {"terminal_id": terminal_id, "cols": message.get("cols"), "rows": message.get("rows")})


async def _handle_terminal_signal(message, terminal_sessions, emit) -> None:
    terminal_id = str(message.get("terminal_id") or "")
    session = terminal_sessions.get(terminal_id) if terminal_sessions else None
    if session is None or emit is None:
        return
    await session.signal(str(message.get("signal") or "interrupt"))


async def _handle_terminal_close(message, terminal_sessions, emit) -> None:
    terminal_id = str(message.get("terminal_id") or "")
    session = terminal_sessions.pop(terminal_id, None) if terminal_sessions is not None else None
    if session is None:
        return
    await session.close()
    if emit is not None:
        await emit("terminal_closed", {"terminal_id": terminal_id, "lane": session.lane})


async def _handle_send_message(runtime: SessionRuntime, message: dict):
    try:
        data = SendMessageIn(**message)
    except Exception as exc:
        await runtime.emit(
            "error",
            {"code": "INVALID_REQUEST", "message": f"invalid message payload: {exc}"},
        )
        return

    try:
        await runtime.run(data.content, lane=data.lane)
    except AgentError as exc:
        await runtime.emit(
            "run_error",
            {
                "code": exc.code,
                "message": exc.message,
                "suggestions": getattr(exc, "suggestions", []),
            },
        )
    except Exception as exc:
        logger.exception("Run execution failed")
        await runtime.emit(
            "run_error",
            {"code": "INTERNAL_ERROR", "message": f"internal error: {exc}"},
        )


def _handle_permission_response(runtime: SessionRuntime, message: dict):
    try:
        data = PermissionResponseIn(**message)
    except Exception as exc:
        logger.warning("Invalid permission response payload: %s", exc)
        return

    matched = runtime.resolve_permission(data.request_id, data.action)
    if not matched:
        logger.warning("Permission request not found: %s", data.request_id)


async def _handle_interrupt_run(runtime: SessionRuntime, message: dict) -> None:
    try:
        data = InterruptRunIn(**message)
    except Exception as exc:
        await runtime.emit(
            "error",
            {"code": "INVALID_REQUEST", "message": f"invalid interrupt payload: {exc}"},
        )
        return

    interrupted = await runtime.interrupt_run(data.run_id)
    if not interrupted:
        await runtime.emit(
            "run_interrupt_rejected",
            {"code": "NO_ACTIVE_RUN", "message": "当前没有可中断的 Agent 运行"},
        )


async def _emit(
    websocket: WebSocket,
    event: str,
    payload: dict[str, Any],
    send_lock: asyncio.Lock,
):
    envelope = WSEnvelope(type=event, data=payload)
    if (
        websocket.client_state != WebSocketState.CONNECTED
        or websocket.application_state != WebSocketState.CONNECTED
    ):
        return
    async with send_lock:
        try:
            await websocket.send_json(envelope.model_dump())
        except RuntimeError as exc:
            if _is_closed_socket_error(exc):
                return
            logger.warning("Failed to push event %s", event, exc_info=True)
        except WebSocketDisconnect:
            return
        except Exception:
            logger.warning("Failed to push event %s", event, exc_info=True)


def _is_closed_socket_error(exc: BaseException) -> bool:
    message = str(exc)
    return (
        "WebSocket is not connected" in message
        or "close message has been sent" in message
        or "not connected" in message
    )
