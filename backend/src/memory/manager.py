"""Context compaction and workspace memory coordination."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..agent.providers import entries_to_messages
from ..llm.events import DoneEvent, Message, TextDeltaEvent
from ..storage.models import Entry
from ..storage.session_storage import estimate_tokens

logger = logging.getLogger(__name__)


SUMMARY_SYSTEM_PROMPT = """你是一个编程 Agent 的上下文摘要器。你只能输出结构化摘要，不能继续执行任务，也不能调用工具。保留准确的文件路径、函数名、命令、错误信息和用户约束。"""

SUMMARY_PROMPT = """请把下面的历史整理成可以让另一个编程 Agent 无损继续工作的摘要。

严格使用以下章节，所有章节都必须保留：

## 目标
## 约束与偏好
## 已完成
## 进行中
## 阻塞与未知
## 关键决策
## 相关文件
## 下一步

使用简短条目，不要描述摘要过程。若某一节没有内容，写“（无）”。"""


def _message_tokens(message: Message) -> int:
    payload = message.content or ""
    if message.tool_calls:
        payload += json.dumps([call.arguments for call in message.tool_calls], ensure_ascii=False)
    return estimate_tokens(payload)


def _entry_tokens(entry: Entry) -> int:
    return sum(_message_tokens(message) for message in entries_to_messages([entry]))


def _serialize(messages: list[Message]) -> str:
    lines: list[str] = []
    for message in messages:
        if message.role == "tool":
            lines.append(f"[工具结果] {message.content or ''}")
        elif message.role == "assistant":
            calls = ""
            if message.tool_calls:
                calls = "\n工具调用: " + "; ".join(
                    f"{call.name}({json.dumps(call.arguments, ensure_ascii=False)})"
                    for call in message.tool_calls
                )
            lines.append(f"[Agent] {message.content or ''}{calls}")
        else:
            lines.append(f"[{message.role}] {message.content or ''}")
    return "\n\n".join(lines)


class MemoryManager:
    """Owns context projection, compaction, and project context loading."""

    def __init__(
        self,
        storage,
        lane_manager,
        llm_client,
        workspace: Path | str,
        max_context_tokens: int = 8000,
        reserve_tokens: int = 2000,
        keep_recent_tokens: int = 3000,
        summary_max_tokens: int = 1200,
        threshold_ratio: float = 0.8,
    ) -> None:
        self.storage = storage
        self.lane_manager = lane_manager
        self.llm_client = llm_client
        self.workspace = Path(workspace).expanduser().resolve()
        self.max_context_tokens = max(1000, int(max_context_tokens))
        self.reserve_tokens = max(0, int(reserve_tokens))
        self.keep_recent_tokens = max(500, int(keep_recent_tokens))
        self.summary_max_tokens = max(256, int(summary_max_tokens))
        self.threshold_ratio = min(0.99, max(0.5, float(threshold_ratio)))

    def project_context(self, lane: str) -> list[Message]:
        leaf_id = self.lane_manager.get_lane(lane).leaf_id
        if leaf_id is None:
            return []
        return entries_to_messages(
            self.storage.get_context_window(leaf_id, self.max_context_tokens)
        )

    def estimated_tokens(self, lane: str) -> int:
        return sum(_message_tokens(message) for message in self.project_context(lane))

    def budget_status(self, lane: str, estimated_tokens: int | None = None) -> dict[str, int | float]:
        used_tokens = (
            self.estimated_tokens(lane)
            if estimated_tokens is None
            else max(0, int(estimated_tokens))
        )
        threshold_tokens = min(
            max(1, self.max_context_tokens - self.reserve_tokens),
            max(1, int(self.max_context_tokens * self.threshold_ratio)),
        )
        return {
            "used_tokens": used_tokens,
            "max_tokens": self.max_context_tokens,
            "reserve_tokens": self.reserve_tokens,
            "threshold_tokens": threshold_tokens,
            "remaining_tokens": max(0, self.max_context_tokens - used_tokens),
            "utilization_ratio": round(used_tokens / self.max_context_tokens, 4),
        }

    async def compact_if_needed(
        self, lane: str, *, reason: str = "threshold", force: bool = False
    ) -> dict[str, Any] | None:
        leaf_id = self.lane_manager.get_lane(lane).leaf_id
        if leaf_id is None:
            return None
        effective = self.storage.get_context_entries(leaf_id)
        total_tokens = sum(_entry_tokens(entry) for entry in effective)
        threshold = min(
            max(1, self.max_context_tokens - self.reserve_tokens),
            max(1, int(self.max_context_tokens * self.threshold_ratio)),
        )
        if not force and total_tokens <= max(1, threshold):
            return None

        previous_summary = ""
        start_index = 0
        if effective and effective[0].entry_type == "compaction":
            previous_summary = effective[0].content if isinstance(effective[0].content, str) else ""
            start_index = 1
        if len(effective) - start_index < 2:
            return {"status": "noop", "reason": "没有足够的历史可以压缩"}

        keep_tokens = self.keep_recent_tokens
        tail_start = len(effective)
        used = 0
        while tail_start > start_index:
            candidate = effective[tail_start - 1]
            cost = _entry_tokens(candidate)
            if tail_start < len(effective) and used + cost > keep_tokens:
                break
            used += cost
            tail_start -= 1
        while tail_start > start_index and effective[tail_start].role == "tool":
            tail_start -= 1
        if tail_start <= start_index:
            return {"status": "noop", "reason": "最近消息已经占满保留预算"}

        to_summarize = effective[start_index:tail_start]
        retained = effective[tail_start:]
        if not to_summarize:
            return {"status": "noop", "reason": "没有可压缩消息"}

        conversation = _serialize(entries_to_messages(to_summarize))
        prompt = f"{SUMMARY_PROMPT}\n\n<conversation>\n{conversation}\n</conversation>"
        if previous_summary:
            prompt += (
                "\n\n<previous-summary>\n"
                f"{previous_summary}\n</previous-summary>\n\n"
                "这是已有摘要。保留仍然有效的目标、约束、决策和未完成工作，以新历史为准更新冲突内容。"
            )

        try:
            summary, usage = await self._summarize(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("上下文压缩摘要失败: %s", exc)
            return {"status": "failed", "reason": str(exc), "tokens_before": total_tokens}
        if not summary.strip():
            return {"status": "failed", "reason": "摘要为空", "tokens_before": total_tokens}

        metadata = {
            "reason": reason,
            "covered_entry_ids": [entry.id for entry in to_summarize],
            "retained_entry_ids": [entry.id for entry in retained],
            "first_kept_entry_id": retained[0].id if retained else None,
            "tokens_before": total_tokens,
            "summary_tokens": estimate_tokens(summary),
            "usage": usage,
        }
        compaction = Entry(
            parent=leaf_id,
            lane=lane,
            role="assistant",
            content=summary.strip(),
            entry_type="compaction",
            metadata=metadata,
        )
        try:
            await self.storage.append_message(compaction)
            self.lane_manager.update_lane(lane, compaction.id)
        except Exception as exc:  # noqa: BLE001 - 压缩失败不能破坏原始历史
            logger.warning("上下文压缩结果落盘失败: %s", exc)
            return {"status": "failed", "reason": str(exc), "tokens_before": total_tokens}
        return {
            "status": "completed",
            "entry_id": compaction.id,
            "reason": reason,
            "tokens_before": total_tokens,
            "summary_tokens": metadata["summary_tokens"],
            "retained_count": len(retained),
            "covered_count": len(to_summarize),
            "usage": usage,
            "memory": self.budget_status(lane),
        }

    async def _summarize(self, prompt: str) -> tuple[str, dict[str, int]]:
        messages = [
            Message(role="system", content=SUMMARY_SYSTEM_PROMPT),
            Message(role="user", content=prompt),
        ]
        parts: list[str] = []
        usage: dict[str, int] = {}
        async for event in self.llm_client.chat(
            messages, tools=None, max_tokens=self.summary_max_tokens, temperature=0.1
        ):
            if isinstance(event, TextDeltaEvent):
                parts.append(event.text)
            elif isinstance(event, DoneEvent):
                usage = {key: int(value) for key, value in event.usage.items() if isinstance(value, (int, float))}
        return "".join(parts), usage

    def project_memory(self) -> str:
        from .project import load_project_context

        return load_project_context(self.workspace)
