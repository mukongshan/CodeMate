"""树形对话历史的存储与查询。

对应功能设计 02-树形对话历史系统（数据模型与查询算法）、
12-存储层设计（JSONL 物理格式、加载策略、崩溃恢复）。

两条硬性实现约束（12 号文档四节 / 02 号文档 6.1 节）：

1. **所有树查询必须走内存索引，绝不对 JSONL 做线性扫描。** 启动时一次性全量
   加载建好 ``_entries`` / ``_children_index`` / ``_lane_index``，之后文件只在
   append 时被触碰，不参与任何读路径。
2. **写入用单 session 写锁序列化。** 业务规则已保证任意时刻只有一个 Run 在跑
   （03 号文档 7.3 节），所以一个全局锁足够，不需要按 Lane 分别加锁。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .models import Entry

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data/sessions")

# 上下文窗口的默认 token 预算。留给模型输出的余量在 LLM 层用 max_tokens 控制，
# 这里只管历史消息占多少。
DEFAULT_MAX_CONTEXT_TOKENS = 8000


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数。

    02 号文档 4.2 节给的简化方法是 ``len(content) / 4``。这里对中文做了修正：
    英文约 4 字符/token，中文约 1 token/字，一律按 /4 算会严重低估中文内容，
    导致实际请求超出模型上下文窗口。按字符是否 ASCII 分别计权更稳。

    不引入 tiktoken：它对 DeepSeek 这类非 OpenAI 模型的分词并不准确，
    多一个重量级依赖换来的精度提升在"控制上下文长度"这个用途上不值得。
    """
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ch.isascii())
    wide_chars = len(text) - ascii_chars
    return ascii_chars // 4 + wide_chars + 1


def _entry_token_cost(entry: Entry) -> int:
    """估算一条 Entry 在请求里占的 token。"""
    from .models import TextBlock, ToolResultBlock, ToolUseBlock

    if isinstance(entry.content, str):
        return estimate_tokens(entry.content) + estimate_tokens(
            entry.reasoning_content or ""
        )

    total = estimate_tokens(entry.reasoning_content or "")
    for block in entry.content:
        if isinstance(block, TextBlock):
            total += estimate_tokens(block.text)
        elif isinstance(block, ToolUseBlock):
            # 工具名 + 参数 JSON 都要计入
            total += estimate_tokens(block.name)
            total += estimate_tokens(json.dumps(block.arguments, ensure_ascii=False))
        elif isinstance(block, ToolResultBlock):
            total += estimate_tokens(block.content)
    return total


class SessionStorage:
    """单个 session 的树形历史：内存索引 + JSONL 落盘。"""

    def __init__(
        self,
        session_id: str,
        data_dir: Path | str = DEFAULT_DATA_DIR,
        *,
        path: Path | str | None = None,
    ) -> None:
        self.session_id = session_id
        self.data_dir = Path(data_dir)
        self.path = Path(path) if path is not None else self.data_dir / f"{session_id}.jsonl"

        self._entries: dict[str, Entry] = {}
        self._children_index: dict[str, list[str]] = defaultdict(list)
        self._lane_index: dict[str, list[str]] = defaultdict(list)
        self._next_seq = 1
        self._write_lock = asyncio.Lock()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    # --- 加载 ---------------------------------------------------------------

    def _load(self) -> None:
        """启动时全量加载并建索引，跳过损坏行（12 号文档 6.1 节）。

        损坏只可能出现在"正在写的最后一行"——已 flush 的历史行不受影响。
        丢弃半截行是正确语义：那次 append 相当于没发生过。
        """
        if not self.path.exists():
            return

        max_seq = 0
        skipped = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = Entry.from_jsonl_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                    skipped += 1
                    logger.warning(
                        "跳过损坏的历史行 #%d（可能是崩溃时的半截写入）: %s",
                        lineno,
                        exc,
                    )
                    continue

                # 重复 id 必须显式跳过：直接覆盖会让 children_index 里同一个子节点
                # 出现两次，前端画出一条不存在的分支。append-only + 单写者下不该发生，
                # 但文件被外部编辑过就可能出现。
                if entry.id in self._entries:
                    skipped += 1
                    logger.warning("跳过重复 id 的行 #%d: %s", lineno, entry.id)
                    continue

                self._index_entry(entry)
                max_seq = max(max_seq, entry.seq)

        self._next_seq = max_seq + 1
        if skipped:
            logger.warning(
                "session %s 加载完成，跳过 %d 行损坏数据，恢复 %d 个节点",
                self.session_id,
                skipped,
                len(self._entries),
            )

    def _index_entry(self, entry: Entry) -> None:
        self._entries[entry.id] = entry
        if entry.parent is not None:
            self._children_index[entry.parent].append(entry.id)
        self._lane_index[entry.lane].append(entry.id)

    # --- 写入 ---------------------------------------------------------------

    async def append_message(self, entry: Entry) -> Entry:
        """分配 seq、写 JSONL、更新内存索引。持写锁保证不交错。"""
        async with self._write_lock:
            entry.seq = self._next_seq
            self._next_seq += 1
            # 先落盘再更新索引：写失败时内存状态不会与文件不一致
            await asyncio.to_thread(self._append_to_file, entry)
            self._index_entry(entry)
            return entry

    def _append_to_file(self, entry: Entry) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_jsonl_dict(), ensure_ascii=False) + "\n")
            f.flush()

    # --- 查询（全部走内存索引） ---------------------------------------------

    def get_entry(self, entry_id: str) -> Optional[Entry]:
        return self._entries.get(entry_id)

    def get_children(self, entry_id: str) -> list[str]:
        return list(self._children_index.get(entry_id, []))

    def get_lane_entries(self, lane: str) -> list[str]:
        """某个 Lane 标签下创建的所有节点 id。

        注意这是**创建归属标签**的查询，不是路径查询——不要用它推导 Lane 路径
        （见 03 号文档 1.5.2 节）。路径查询用 :meth:`get_history_path`。
        """
        return list(self._lane_index.get(lane, []))

    def all_entries(self) -> list[Entry]:
        """按 seq 升序返回全部节点，供 API 首次加载时渲染树。"""
        return sorted(self._entries.values(), key=lambda e: e.seq)

    def get_history_path(self, leaf_id: str) -> list[Entry]:
        """从叶子沿 parent 走到根，返回根→叶顺序（02 号文档 3.2 节）。

        只依赖 parent 指针，parent 为 None 时自然停止——所以 Lane 不需要额外
        记录 root 在哪（03 号文档 1.5.3 节）。
        """
        path: list[Entry] = []
        seen: set[str] = set()
        current: Optional[str] = leaf_id
        while current is not None:
            if current in seen:
                # 正常写入路径不可能造成环；真出现了说明数据被外部破坏，
                # 记日志截断而不是无限循环。
                logger.error("检测到 parent 链成环，节点 %s，已截断", current)
                break
            entry = self._entries.get(current)
            if entry is None:
                break
            seen.add(current)
            path.append(entry)
            current = entry.parent
        path.reverse()
        return path

    def find_common_ancestor(self, id_a: str, id_b: str) -> Optional[str]:
        """两个节点的最近公共祖先（02 号文档 3.3 节）。

        实现上取 A 到根的路径存成集合，再沿 B 往上走，第一个命中的就是最近公共
        祖先。注意"两个叶子中一个是另一个的祖先"这种情况也能正确返回那个祖先，
        对应 03 号文档 1.5.4 节的边界处理。
        """
        ancestors_a = {e.id for e in self.get_history_path(id_a)}
        if not ancestors_a:
            return None
        current: Optional[str] = id_b
        seen: set[str] = set()
        while current is not None:
            if current in ancestors_a:
                return current
            if current in seen:
                break
            seen.add(current)
            entry = self._entries.get(current)
            if entry is None:
                break
            current = entry.parent
        return None

    def get_context_entries(self, leaf_id: str) -> list[Entry]:
        """返回当前叶节点对应的有效上下文投影，保留最近压缩摘要。"""
        full_path = self.get_history_path(leaf_id)
        latest_index = -1
        for index in range(len(full_path) - 1, -1, -1):
            if full_path[index].entry_type == "compaction":
                latest_index = index
                break
        if latest_index < 0:
            return full_path

        compaction = full_path[latest_index]
        retained_ids = set(compaction.metadata.get("retained_entry_ids") or [])
        retained = [entry for entry in full_path[:latest_index] if entry.id in retained_ids]
        return [compaction, *retained, *full_path[latest_index + 1 :]]

    def get_context_window(
        self, leaf_id: str, max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS
    ) -> list[Entry]:
        """从有效上下文投影中保留最新消息，并确保工具调用成对。"""
        full_path = self.get_context_entries(leaf_id)
        if not full_path:
            return []

        anchor: list[Entry] = []
        start_index = 0
        if full_path[0].entry_type == "compaction":
            anchor = [full_path[0]]
            start_index = 1
        selected: list[Entry] = []
        used = sum(_entry_token_cost(entry) for entry in anchor)
        for entry in reversed(full_path[start_index:]):
            cost = _entry_token_cost(entry)
            if selected and used + cost > max_tokens:
                break
            selected.append(entry)
            used += cost
        selected.reverse()
        return self._repair_tool_pairing([*anchor, *selected])

    @staticmethod
    def _repair_tool_pairing(entries: list[Entry]) -> list[Entry]:
        """丢掉开头孤立的 tool 消息，保证首条不是无主的 tool_result。

        截断只会从头部切掉消息，所以孤立情况只出现在开头：一条 role=tool 的
        Entry 的前置 assistant 被切走了。把这些开头的 tool 消息一并丢掉即可。
        """
        start = 0
        while start < len(entries) and entries[start].role == "tool":
            start += 1
        return entries[start:] if start else entries

    # --- 统计 ---------------------------------------------------------------

    def is_fork_point(self, entry_id: str) -> bool:
        """子节点数 > 1 即为分叉点（07 号文档 4.3 节）。"""
        return len(self._children_index.get(entry_id, [])) > 1

    def entry_count(self) -> int:
        return len(self._entries)

    def delete_files(self) -> None:
        """删除该 session 的历史文件。供 API 的 DELETE 端点使用。"""
        self.path.unlink(missing_ok=True)
