"""结构化日志。

对应功能设计 11-日志与可观测性，代码设计 03 号文档七节。

**不实现日志轮转和独立的日志查看器 UI**（03 号文档七节明确排除）：
文件无限增长是可接受的，`cat logs/*.jsonl` 就够用。

事件名统一用 11 号文档 4.1 节的事件表，不发明新前缀——这样日志、
WebSocket 事件、前端三处对同一件事的叫法是一致的。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 永不写进日志的字段名（11 号文档 10.1 节）
_REDACT_KEYS = frozenset(
    {"api_key", "apikey", "password", "token", "secret", "authorization"}
)


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _redact(fields: dict) -> dict:
    """把敏感字段替换成占位符。"""
    cleaned: dict[str, Any] = {}
    for key, value in fields.items():
        if key.lower() in _REDACT_KEYS:
            cleaned[key] = "***"
        elif isinstance(value, dict):
            cleaned[key] = _redact(value)
        else:
            cleaned[key] = value
    return cleaned


class StructuredLogger:
    """一个 session 一个日志文件，每行一个 JSON 事件。"""

    def __init__(self, session_id: str, log_dir: Path | str = Path("logs")) -> None:
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.agent_log = self.log_dir / f"{session_id}_agent.jsonl"
        # 由 api/ws.py 注入，把日志条目转发到前端
        self.ui_callback: Optional[Callable[[dict], None]] = None

    def log(self, level: LogLevel, event: str, **fields: Any) -> None:
        entry = {
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "level": level.value,
            "event": event,
            **_redact(fields),
        }
        self._write(entry, self.agent_log)

        if self.ui_callback is not None:
            try:
                self.ui_callback(entry)
            except Exception:  # noqa: BLE001 - 转发失败不影响落盘
                logger.warning("日志转发到前端失败", exc_info=True)

        if level in (LogLevel.WARNING, LogLevel.ERROR):
            logger.log(
                logging.WARNING if level is LogLevel.WARNING else logging.ERROR,
                "%s %s",
                event,
                {k: v for k, v in entry.items() if k not in ("timestamp", "session_id", "level", "event")},
            )

    def debug(self, event: str, **fields: Any) -> None:
        self.log(LogLevel.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self.log(LogLevel.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self.log(LogLevel.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.log(LogLevel.ERROR, event, **fields)

    def log_permission_decision(
        self, tool_name: str, args: dict, decision: Any
    ) -> None:
        """权限决策写独立的审计文件（09 号文档 7.1 节）。"""
        entry = {
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "event": "permission_decision",
            "tool": tool_name,
            "args": _redact(args),
            "allowed": decision.allowed,
            "reason": decision.reason,
            "user_confirmed": decision.user_confirmed,
            "auto_approved": decision.auto_approved,
        }
        self._write(entry, self.log_dir / "permissions.jsonl")

    @staticmethod
    def _write(entry: dict, path: Path) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.warning("写日志失败: %s", path, exc_info=True)


def setup_logging(debug: bool = False) -> None:
    """配置标准库 logging，供开发时看控制台输出。"""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx 每次请求都打一行 INFO，调 LLM 时噪音太大
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
