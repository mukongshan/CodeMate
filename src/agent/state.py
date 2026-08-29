"""Agent 运行状态与结果类型。

对应功能设计 04-Agent主循环 3.1/3.2 节，代码设计 01 号文档五节。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentState(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    CALLING_LLM = "calling_llm"
    EXECUTING_TOOL = "executing_tool"
    WAITING_PERMISSION = "waiting_permission"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class RunContext:
    """一次 run 的执行上下文。"""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    lane: str = "main"
    user_message_id: Optional[str] = None
    state: AgentState = AgentState.IDLE
    iteration: int = 0
    total_tokens: int = 0
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class RunResult:
    """一次 run 的结果。

    字段是父 Agent 和子 Agent 共用的：``final_message_id`` 对子 Agent 无意义
    （它不写树）所以可为 None，``touched_paths``/``final_text`` 是子 Agent
    打包结论时要用的（15 号文档 7.1 节）。
    """

    run_id: str
    status: str  # 'completed' | 'partial' | 'error' | 'aborted'
    final_message_id: Optional[str] = None
    final_text: str = ""
    iterations: int = 0
    total_tokens: int = 0
    duration: float = 0.0
    touched_paths: list[str] = field(default_factory=list)
    error: Optional[str] = None
