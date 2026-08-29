"""错误类型体系。

对应功能设计 08-错误处理机制。核心原则（08 号文档一节）：

- 工具错误不中断主循环：转成消息回传给 LLM，让它自我修正
- API 错误按 ``retryable`` 决定重试还是中断
- 系统错误记录日志后中断

按代码设计 01 号文档六节的决定，这里用 ``AgentError`` 异常体系而不是
``Result[T, E]`` 泛型：Python 的 async 函数天然靠异常传播错误，包一层
Result 反而要在每个 await 点手动判断。
"""

from __future__ import annotations

import traceback as _traceback
from dataclasses import dataclass, field
from typing import Optional


# eq=False 保留 Exception 默认的按身份比较与可哈希性；dataclass 默认生成的
# __eq__ 会把 __hash__ 置为 None，异常对象被放进 set/dict 时会炸。
@dataclass(eq=False)
class AgentError(Exception):
    """所有业务错误的基类。

    ``code`` 是稳定的机器可读标识，API 层直接透出给前端（见 02-API设计 四节），
    所以新增错误码时不要复用已有名字。
    """

    message: str
    code: str
    details: Optional[dict] = None
    suggestions: Optional[list[str]] = None

    def __post_init__(self) -> None:
        # dataclass 不会调用 Exception.__init__，不补这一行的话 self.args 是空的，
        # 标准库里任何依赖 args 的地方（比如 traceback 打印）都会丢失信息。
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message

    def to_llm_text(self) -> str:
        """转成回传给 LLM 的文本（08 号文档 4.1 节 to_llm_message）。

        建议列表要一起带上——LLM 看到"用 glob 找找文件"这类提示，
        下一轮就能自己纠正，这是"工具错误不中断"策略生效的关键。
        """
        lines = [f"错误: {self.message}"]
        if self.suggestions:
            lines.append("")
            lines.append("建议:")
            lines.extend(f"  {i}. {s}" for i, s in enumerate(self.suggestions, 1))
        return "\n".join(lines)

    def to_api_dict(self) -> dict:
        """转成 02-API设计 四节约定的错误响应体。"""
        payload: dict = {"code": self.code, "message": self.message}
        if self.suggestions:
            payload["suggestions"] = self.suggestions
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(eq=False)
class ToolExecutionError(AgentError):
    """工具执行失败。不中断主循环。"""

    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)

    def to_llm_text(self) -> str:
        lines = [f"工具 {self.tool_name} 执行失败: {self.message}"]
        if self.suggestions:
            lines.append("")
            lines.append("建议:")
            lines.extend(f"  {i}. {s}" for i, s in enumerate(self.suggestions, 1))
        return "\n".join(lines)


@dataclass(eq=False)
class PermissionDeniedError(AgentError):
    """权限检查未通过。不中断主循环，回传给 LLM 说明原因。"""

    tool_name: str = ""
    permission_level: str = ""
    reason: str = ""


@dataclass(eq=False)
class ValidationError(AgentError):
    """工具参数校验失败。不中断主循环。"""

    tool_name: str = ""
    validation_errors: list[str] = field(default_factory=list)

    def to_llm_text(self) -> str:
        lines = [f"工具 {self.tool_name} 参数校验失败:"]
        lines.extend(f"  - {e}" for e in self.validation_errors)
        return "\n".join(lines)


@dataclass(eq=False)
class LLMAPIError(AgentError):
    """LLM API 调用失败。``retryable`` 决定是重试还是中断（08 号文档 5.2 节）。"""

    provider: str = ""
    retryable: bool = False
    retry_after: Optional[int] = None


@dataclass(eq=False)
class SystemError(AgentError):
    """系统级错误。记录日志并中断执行。"""

    source: str = ""
    traceback: str = ""


@dataclass(eq=False)
class SessionNotFoundError(AgentError):
    """session 不存在。API 层映射为 404。"""

    session_id: str = ""


@dataclass(eq=False)
class LaneNotFoundError(AgentError):
    """Lane 不存在。API 层映射为 404。"""

    lane: str = ""


# --- 错误码常量 -------------------------------------------------------------
# 集中定义避免各处写字符串字面量拼错。

CODE_FILE_NOT_FOUND = "FILE_NOT_FOUND"
CODE_FILE_TOO_LARGE = "FILE_TOO_LARGE"
CODE_NOT_A_FILE = "NOT_A_FILE"
CODE_BINARY_FILE = "BINARY_FILE"
CODE_DECODE_FAILED = "DECODE_FAILED"
CODE_PATH_OUTSIDE_WORKSPACE = "PATH_OUTSIDE_WORKSPACE"
CODE_SYSTEM_PATH_FORBIDDEN = "SYSTEM_PATH_FORBIDDEN"
CODE_NO_MATCH = "NO_MATCH"
CODE_MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
CODE_COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
CODE_DANGEROUS_COMMAND = "DANGEROUS_COMMAND"
CODE_TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
CODE_VALIDATION_ERROR = "VALIDATION_ERROR"
CODE_PERMISSION_DENIED = "PERMISSION_DENIED"
CODE_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
CODE_LANE_NOT_FOUND = "LANE_NOT_FOUND"
CODE_LANE_EXISTS = "LANE_EXISTS"
CODE_LANE_PROTECTED = "LANE_PROTECTED"
CODE_INVALID_LANE_NAME = "INVALID_LANE_NAME"
CODE_ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"
CODE_RUN_IN_PROGRESS = "RUN_IN_PROGRESS"
CODE_SUBAGENT_DEPTH_EXCEEDED = "SUBAGENT_DEPTH_EXCEEDED"
CODE_SUBAGENT_TIMEOUT = "SUBAGENT_TIMEOUT"
CODE_LLM_ERROR = "LLM_ERROR"
CODE_UNKNOWN = "UNKNOWN_ERROR"


def wrap_unexpected(exc: BaseException, source: str) -> SystemError:
    """把未预期的异常收敛成 SystemError，保留完整 traceback 供日志排查。"""
    return SystemError(
        message=str(exc) or exc.__class__.__name__,
        code=CODE_UNKNOWN,
        source=source,
        traceback="".join(
            _traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
    )
