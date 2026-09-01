"""API 层的请求/响应 schema。

对应代码设计 02 号文档 3.3 节。

这里的模型只用于**服务端内部**构造 payload 时的类型检查，不要求前端引入
同一套 schema——前端用手写 TypeScript interface 对齐即可。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# --- WebSocket 信封 ---------------------------------------------------------


class WSEnvelope(BaseModel):
    """所有服务端事件统一包一层，前端只需一个 switch(msg.type) 分发。"""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


# --- 客户端 → 服务端 --------------------------------------------------------


class SendMessageIn(BaseModel):
    type: Literal["send_message"]
    content: str
    lane: Optional[str] = None


class PermissionResponseIn(BaseModel):
    type: Literal["permission_response"]
    request_id: str
    action: Literal["allow_once", "allow_always", "deny"]


class InterruptRunIn(BaseModel):
    """中断当前主 Agent 运行；run_id 为空时中断本会话当前运行。"""

    type: Literal["interrupt_run"]
    run_id: Optional[str] = None


# --- 服务端 → 客户端的 data 部分 --------------------------------------------


class TextDeltaData(BaseModel):
    message_id: str
    text: str


class ToolCallEndData(BaseModel):
    call_id: str
    status: Literal["success", "error"]
    result: str


class PermissionRequestData(BaseModel):
    request_id: str
    tool_name: str
    args: dict
    risk_level: Literal["low", "medium", "high"]
    warning: str


class SubagentDoneData(BaseModel):
    subagent_id: str
    status: Literal["completed", "partial", "error", "cancelled", "timeout"]
    content: str
    details: dict


class StatusUpdateData(BaseModel):
    state: str
    current_lane: Optional[str] = None
    current_operation: Optional[str] = None


class LaneCreatedData(BaseModel):
    lane: str
    from_id: Optional[str] = None


class LaneSwitchedData(BaseModel):
    lane: str
    leaf_id: Optional[str] = None


class LaneDeletedData(BaseModel):
    lane: str


# --- REST 请求体 ------------------------------------------------------------


class CreateSessionIn(BaseModel):
    session_id: Optional[str] = None
    workspace: Optional[str] = None
    workspace_id: Optional[str] = None
    title: Optional[str] = None


class CompactSessionIn(BaseModel):
    lane: Optional[str] = None


class CreateWorkspaceIn(BaseModel):
    path: str
    title: Optional[str] = None


class RenameIn(BaseModel):
    title: str


class RenameLaneIn(BaseModel):
    name: str


class CreateLaneIn(BaseModel):
    name: str
    from_id: Optional[str] = None
    description: Optional[str] = None


class WriteWorkspaceFileIn(BaseModel):
    path: str
    content: str
    encoding: Optional[str] = None
    expected_revision: Optional[str] = None


class GitPathsIn(BaseModel):
    paths: list[str] = Field(default_factory=list)


class GitCommitIn(BaseModel):
    message: str


class CheckpointIn(BaseModel):
    paths: Optional[list[str]] = None
    allow_blocked: bool = False


class RestoreCheckpointIn(BaseModel):
    checkpoint_id: str
    discard_changes: bool = False


class PublishLaneIn(BaseModel):
    target_branch: str
    mode: Literal["branch", "squash"] = "branch"
    base_branch: Optional[str] = None


class IntegrateLaneIn(BaseModel):
    target_branch: Optional[str] = None
    strategy: Literal["merge", "ff", "squash"] = "merge"


class UpdatePermissionGateIn(BaseModel):
    command_blacklist: list[str] = Field(default_factory=list)


# --- REST 错误响应 ----------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str
    suggestions: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody
