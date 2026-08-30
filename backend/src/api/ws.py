from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..errors.types import AgentError
from .schemas import PermissionResponseIn, SendMessageIn, WSEnvelope
from .session_service import SessionManager, SessionRuntime

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info("WebSocket connected: session=%s", session_id)
    send_lock = asyncio.Lock()
    active_tasks: set[asyncio.Task[None]] = set()

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
            task = await _handle_message(runtime, message)
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
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        if runtime.clear_emitter(connection_id):
            runtime.fail_pending_permissions("connection closed")


async def _handle_message(runtime: SessionRuntime, message: dict):
    msg_type = message.get("type")

    if msg_type == "send_message":
        return asyncio.create_task(_handle_send_message(runtime, message))
    elif msg_type == "permission_response":
        _handle_permission_response(runtime, message)
    else:
        logger.warning("Unknown websocket message type: %s", msg_type)
    return None


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
        result = await runtime.run(data.content, lane=data.lane)
        await runtime.emit(
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
