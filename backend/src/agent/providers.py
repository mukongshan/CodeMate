"""上下文读写抽象。

对应功能设计 04-Agent主循环 4.0 节。

**这是整个项目最值得在动手写代码前想清楚的接口。** 主循环读写上下文必须通过
这个抽象，不能直接调 ``SessionStorage``——因为子 Agent 复用同一套循环，但跑在
纯内存列表上，不能碰父树（不落盘、不动 Lane 指针）。如果循环里到处内联
``self.storage.append_message(...)``，等实现子 Agent 时就得把每个调用点翻出来改。
"""

from __future__ import annotations

from typing import Optional, Protocol

from ..llm.events import Message, ToolCall
from ..storage.lane_manager import LaneManager
from ..storage.models import (
    Entry,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from ..storage.session_storage import SessionStorage


class MessageProvider(Protocol):
    """主循环读写上下文的抽象接口，不关心底层是树还是内存列表。"""

    def get_context(self) -> list[Message]: ...

    async def append(self, message: Message) -> Optional[str]:
        """追加一条消息，返回节点 id（内存实现返回 None）。"""
        ...


# --- Entry ↔ Message 转换 ---------------------------------------------------


def entry_to_message(entry: Entry) -> Message:
    """把树节点转成 LLM 协议消息（01 号文档八节）。"""
    if isinstance(entry.content, str):
        role = "system" if entry.entry_type in {"compaction", "branch_summary"} else entry.role
        content = entry.content
        if entry.entry_type == "compaction":
            content = "[会话压缩摘要]\n" + content
        elif entry.entry_type == "branch_summary":
            content = "[分支摘要]\n" + content
        return Message(role=role, content=content)  # type: ignore[arg-type]

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResultBlock] = []

    for block in entry.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            tool_calls.append(
                ToolCall(id=block.id, name=block.name, arguments=block.arguments)
            )
        elif isinstance(block, ToolResultBlock):
            tool_results.append(block)

    if entry.role == "tool":
        # 一个 Entry 可能打包了多个并行工具的结果，但 LLM 协议要求每个
        # tool_call_id 一条独立消息。这里只能返回第一条——完整展开由
        # expand_tool_entry 处理，get_context 会调它。
        if tool_results:
            first = tool_results[0]
            return Message(
                role="tool", content=first.content, tool_call_id=first.tool_call_id
            )
        return Message(role="tool", content="", tool_call_id=None)

    return Message(
        role=entry.role,  # type: ignore[arg-type]
        content="\n".join(p for p in text_parts if p) or None,
        tool_calls=tool_calls or None,
    )


def expand_tool_entry(entry: Entry) -> list[Message]:
    """把一个打包了 N 个工具结果的 tool Entry 展开成 N 条协议消息。

    树里存的是"一次 assistant 回复的所有工具结果打包成一条消息"
    （02 号文档 2.2 节的单 parent 约束），但 OpenAI 协议要求每个 tool_call_id
    对应一条独立的 role=tool 消息。所以存储形态和协议形态在这里做转换——
    这正是把两套类型分开的原因。
    """
    if isinstance(entry.content, str):
        return [Message(role="tool", content=entry.content)]

    messages: list[Message] = []
    for block in entry.content:
        if isinstance(block, ToolResultBlock):
            messages.append(
                Message(
                    role="tool",
                    content=block.content,
                    tool_call_id=block.tool_call_id,
                )
            )
    return messages


def entries_to_messages(entries: list[Entry]) -> list[Message]:
    """批量转换，自动展开打包的工具结果。"""
    messages: list[Message] = []
    for entry in entries:
        if entry.role == "tool":
            messages.extend(expand_tool_entry(entry))
        else:
            messages.append(entry_to_message(entry))
    return repair_message_sequence(messages)


def repair_message_sequence(messages: list[Message]) -> list[Message]:
    """修复被上下文裁剪切断的 OpenAI 消息序列。

    规则很简单：
    - 允许普通 system/user/assistant 消息直接通过。
    - assistant 带 tool_calls 时，后面必须紧跟同数量、同顺序的 tool 消息。
    - 只要发现最后一轮 tool 链不完整，就把这一轮整体丢掉。
    """
    repaired: list[Message] = []
    pending_tool_ids: list[str] = []
    assistant_start: int | None = None

    def drop_pending_group() -> None:
        nonlocal repaired, pending_tool_ids, assistant_start
        if assistant_start is not None:
            repaired = repaired[:assistant_start]
        pending_tool_ids = []
        assistant_start = None

    idx = 0
    while idx < len(messages):
        message = messages[idx]

        if pending_tool_ids:
            if message.role != "tool":
                drop_pending_group()
                continue
            if message.tool_call_id != pending_tool_ids[0]:
                drop_pending_group()
                continue

            repaired.append(message)
            pending_tool_ids.pop(0)
            if not pending_tool_ids:
                assistant_start = None
            idx += 1
            continue

        if message.role == "assistant" and not message.content and not message.tool_calls:
            idx += 1
            continue

        if message.role == "assistant" and message.tool_calls:
            tool_call_ids = [tc.id for tc in message.tool_calls if tc.id]
            if len(tool_call_ids) != len(message.tool_calls):
                idx += 1
                continue

            repaired.append(message)
            pending_tool_ids = tool_call_ids
            assistant_start = len(repaired) - 1
            idx += 1
            continue

        if message.role == "tool":
            idx += 1
            continue

        repaired.append(message)
        idx += 1

    if pending_tool_ids and assistant_start is not None:
        repaired = repaired[:assistant_start]

    return repaired


def message_to_entry_content(message: Message):
    """把协议消息转成 Entry 的 content 形态。"""
    if message.role == "assistant" and message.tool_calls:
        blocks: list = []
        if message.content:
            blocks.append(TextBlock(text=message.content))
        for tc in message.tool_calls:
            blocks.append(
                ToolUseBlock(id=tc.id, name=tc.name, arguments=tc.arguments)
            )
        return blocks
    return message.content or ""


# --- 两种实现 ---------------------------------------------------------------


class TreeMessageProvider:
    """父 Agent 用：读写真实的 JSONL 树 + Lane 指针。"""

    def __init__(
        self,
        storage: SessionStorage,
        lane_manager: LaneManager,
        lane: str,
        max_context_tokens: int = 8000,
    ) -> None:
        self.storage = storage
        self.lane_manager = lane_manager
        self.lane = lane
        self.max_context_tokens = max_context_tokens

    def get_context_entries(self) -> list[Entry]:
        leaf_id = self.lane_manager.get_lane(self.lane).leaf_id
        if leaf_id is None:
            return []
        return self.storage.get_context_entries(leaf_id)

    def get_context(self) -> list[Message]:
        leaf_id = self.lane_manager.get_lane(self.lane).leaf_id
        if leaf_id is None:
            return []
        entries = self.storage.get_context_window(leaf_id, self.max_context_tokens)
        return entries_to_messages(entries)

    async def append(self, message: Message) -> Optional[str]:
        return await self.append_entry(
            role=message.role,  # type: ignore[arg-type]
            content=message_to_entry_content(message),
        )

    async def append_entry(self, role: str, content) -> str:
        """直接以 Entry 形态追加，供需要打包多个工具结果的场景使用。

        两步是一个整体：以当前叶子为 parent 写入新节点，然后把 Lane 指针推进到
        新节点。分叉就是"parent 不是当前叶子"这一件事的自然结果，不需要额外的
        分支创建逻辑（02 号文档 3.1 节）。
        """
        leaf_id = self.lane_manager.get_lane(self.lane).leaf_id
        entry = Entry(parent=leaf_id, lane=self.lane, role=role, content=content)  # type: ignore[arg-type]
        await self.storage.append_message(entry)
        self.lane_manager.update_lane(self.lane, entry.id)
        return entry.id


class EphemeralMessageProvider:
    """子 Agent 用：纯内存 list，生灭随对象，不落盘，不碰父树。

    这个类是子 Agent 上下文隔离的全部实现——正因为主循环只依赖
    ``MessageProvider`` 协议，换掉它就能让同一套循环跑在隔离上下文里
    （15 号文档 6.2 节：中间过程绝对不进父树）。
    """

    def __init__(self, seed_task: str, system_prompt: Optional[str] = None) -> None:
        self._messages: list[Message] = []
        if system_prompt:
            self._messages.append(Message(role="system", content=system_prompt))
        self._messages.append(Message(role="user", content=seed_task))

    def get_context(self) -> list[Message]:
        return list(self._messages)

    async def append(self, message: Message) -> Optional[str]:
        self._messages.append(message)
        return None

    def append_sync(self, message: Message) -> None:
        self._messages.append(message)
