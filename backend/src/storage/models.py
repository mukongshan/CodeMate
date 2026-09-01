"""树形历史与 Lane 指针的数据模型。

对应功能设计 02-树形对话历史系统（Entry 语义）、03-Lane分支管理系统
（LanePointer 语义）、12-存储层设计（JSONL 序列化规格）。

两条必须守住的语义边界：

1. ``Entry.parent`` 是树结构的唯一来源。``Entry.lane`` 只是"这条消息被追加时
   哪个 Lane 是活跃的"这个静态标签，**不能**用来做路径判断
   （见 03 号文档 1.5.2 节：公共祖先段不排他地属于任何一个 Lane）。
2. 一次 assistant 回复并行调用多个工具时，所有 ``ToolResultBlock`` 必须打包进
   **一条** role=tool 的 Entry，不能各自单独成节点，否则会破坏单 parent 树结构
   （见 02 号文档 2.2 节）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

Role = Literal["user", "assistant", "tool"]

# content 里的结构化块类型标记，用于 JSONL 反序列化时区分
_KIND_TOOL_USE = "tool_use"
_KIND_TOOL_RESULT = "tool_result"
_KIND_TEXT = "text"


@dataclass
class ToolUseBlock:
    """assistant 消息里的一次工具调用请求。"""

    id: str
    name: str
    arguments: dict

    def to_dict(self) -> dict:
        return {
            "kind": _KIND_TOOL_USE,
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass
class ToolResultBlock:
    """打包进合成消息的一次工具执行结果。"""

    tool_call_id: str
    content: str
    is_error: bool = False

    def to_dict(self) -> dict:
        return {
            "kind": _KIND_TOOL_RESULT,
            "tool_call_id": self.tool_call_id,
            "content": self.content,
            "is_error": self.is_error,
        }


@dataclass
class TextBlock:
    """assistant 消息里的文本部分。

    单独建一个块类型而不是直接放裸 str，是为了让 ``content`` 列表的元素形状统一，
    JSONL 反序列化时不必区分"这一项是字符串还是 dict"。
    """

    text: str

    def to_dict(self) -> dict:
        return {"kind": _KIND_TEXT, "text": self.text}


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]
EntryContent = Union[str, list[ContentBlock]]


def _block_from_dict(data: dict) -> ContentBlock:
    kind = data.get("kind")
    if kind == _KIND_TOOL_USE:
        return ToolUseBlock(
            id=data["id"], name=data["name"], arguments=data.get("arguments") or {}
        )
    if kind == _KIND_TOOL_RESULT:
        return ToolResultBlock(
            tool_call_id=data["tool_call_id"],
            content=data.get("content", ""),
            is_error=bool(data.get("is_error", False)),
        )
    if kind == _KIND_TEXT:
        return TextBlock(text=data.get("text", ""))
    raise ValueError(f"未知的 content block 类型: {kind!r}")


@dataclass
class Entry:
    """树中的一个节点，粒度是 LLM messages 数组里的一条 message。

    注意 ``seq`` 由 :class:`~src.storage.session_storage.SessionStorage` 在
    append 时统一分配，调用方传进来的值会被覆盖（见 01 号文档字段约束表）。
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent: Optional[str] = None
    lane: str = "main"
    seq: int = 0
    role: Role = "user"
    content: EntryContent = ""
    timestamp: float = field(default_factory=time.time)
    entry_type: str = "message"
    metadata: dict[str, Any] = field(default_factory=dict)
    reasoning_content: Optional[str] = None

    def to_jsonl_dict(self) -> dict:
        """序列化为 JSONL 一行的 dict。"""
        if isinstance(self.content, str):
            content: Union[str, list[dict]] = self.content
        else:
            content = [b.to_dict() for b in self.content]
        return {
            "id": self.id,
            "parent": self.parent,
            "lane": self.lane,
            "seq": self.seq,
            "role": self.role,
            "content": content,
            "timestamp": self.timestamp,
            "entry_type": self.entry_type,
            "metadata": self.metadata,
            "reasoning_content": self.reasoning_content,
        }

    @staticmethod
    def from_jsonl_dict(data: dict) -> "Entry":
        """从 JSONL 一行反序列化。

        缺少必需字段时抛 ``KeyError``/``ValueError``，由调用方
        （``SessionStorage._load``）按 12 号文档 6.1 节的防御性解析策略捕获并跳过。
        """
        raw_content = data["content"]
        content: EntryContent
        if isinstance(raw_content, list):
            content = [_block_from_dict(b) for b in raw_content]
        elif isinstance(raw_content, str):
            content = raw_content
        else:
            raise ValueError(f"content 字段类型非法: {type(raw_content).__name__}")

        role = data["role"]
        if role not in ("user", "assistant", "tool"):
            raise ValueError(f"role 字段取值非法: {role!r}")

        return Entry(
            id=data["id"],
            parent=data["parent"],
            lane=data["lane"],
            seq=int(data["seq"]),
            role=role,
            content=content,
            timestamp=float(data["timestamp"]),
            entry_type=str(data.get("entry_type", "message")),
            metadata=dict(data.get("metadata") or {}),
            reasoning_content=data.get("reasoning_content"),
        )

    def text_preview(self, limit: int = 80) -> str:
        """给树形图节点用的内容摘要（07 号文档 4.2 节：截断至 ~50 字）。"""
        if isinstance(self.content, str):
            text = self.content
        else:
            parts: list[str] = []
            for block in self.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    parts.append(f"[调用 {block.name}]")
                elif isinstance(block, ToolResultBlock):
                    parts.append(block.content)
            text = " ".join(p for p in parts if p)
        text = " ".join(text.split())
        return text if len(text) <= limit else text[:limit] + "…"

    def tool_names(self) -> list[str]:
        """本节点涉及的工具名，用于树节点显示 🔧 read_file 这类标签。"""
        if isinstance(self.content, str):
            return []
        names: list[str] = []
        for block in self.content:
            if isinstance(block, ToolUseBlock):
                names.append(block.name)
        return names

    def has_error(self) -> bool:
        """节点内是否含失败的工具结果，用于节点右上角状态点。"""
        if isinstance(self.content, str):
            return False
        return any(
            isinstance(b, ToolResultBlock) and b.is_error for b in self.content
        )

    def to_api_dict(self) -> dict:
        """前端消费的形态（snake_case，与 02 号 API 设计文档 2.1/3.2 节一致）。

        ``content`` 是 50 字摘要，给树节点直接渲染用（07 号文档 4.2 节）；
        ``full_content`` 才是完整内容，给右侧对话面板和详情侧栏用。
        """
        return {
            "id": self.id,
            "parent": self.parent,
            "lane": self.lane,
            "seq": self.seq,
            "role": self.role,
            "entry_type": self.entry_type,
            "metadata": self.metadata,
            "content": self.text_preview(50),
            "full_content": self.content
            if isinstance(self.content, str)
            else [b.to_dict() for b in self.content],
            "tool_names": self.tool_names(),
            "is_error": self.has_error(),
            "timestamp": self.timestamp,
            "tokens": max(1, len(self.text_preview(10_000)) // 4),
        }


@dataclass
class LanePointer:
    """指向树中某个叶子节点的分支指针。

    只有 ``leaf_id`` 一个核心字段，**不携带任何路径信息**——拿掉所有 Lane，
    树依然完整（见 03 号文档 1.5.1 节）。``created_from`` 仅用于展示血缘，
    不参与树查询。
    """

    lane: str
    leaf_id: Optional[str]
    seq: int
    lane_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    created_from: Optional[str] = None
    description: str = ""
    archived: bool = False

    def to_jsonl_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "lane": self.lane,
            "leaf_id": self.leaf_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "created_from": self.created_from,
            "description": self.description,
            "archived": self.archived,
        }

    @staticmethod
    def from_jsonl_dict(data: dict) -> "LanePointer":
        return LanePointer(
            lane_id=str(data.get("lane_id") or uuid.uuid4().hex),
            lane=data["lane"],
            leaf_id=data["leaf_id"],
            seq=int(data["seq"]),
            timestamp=float(data.get("timestamp", 0.0)),
            created_from=data.get("created_from"),
            description=data.get("description", "") or "",
            archived=bool(data.get("archived", False)),
        )

    def to_api_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "lane": self.lane,
            "leaf_id": self.leaf_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "created_from": self.created_from,
            "description": self.description,
            "archived": self.archived,
        }
