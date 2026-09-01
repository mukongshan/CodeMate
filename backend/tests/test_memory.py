"""记忆系统与上下文压缩测试。"""

from pathlib import Path

import pytest

from src.agent.providers import entries_to_messages
from src.llm.events import DoneEvent, Message, TextDeltaEvent
from src.memory.manager import MemoryManager
from src.memory.project import load_project_context
from src.storage.lane_manager import LaneManager
from src.storage.models import Entry
from src.storage.session_storage import SessionStorage


class FakeSummaryClient:
    async def chat(self, messages, tools=None, **kwargs):
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        yield TextDeltaEvent("## 目标\n- 保留项目目标\n## 下一步\n- 继续实现\n")
        yield DoneEvent("stop", {"prompt_tokens": 20, "completion_tokens": 12})


@pytest.mark.asyncio
async def test_compaction_is_persisted_and_projected(tmp_path: Path):
    storage = SessionStorage("memory-test", tmp_path)
    lanes = LaneManager("memory-test", tmp_path)
    entries = []
    parent = None
    for index in range(10):
        entry = Entry(
            id=f"entry-{index}",
            parent=parent,
            lane="main",
            role="user" if index % 2 == 0 else "assistant",
            content=("project goal and implementation detail " * 16) + str(index),
        )
        await storage.append_message(entry)
        parent = entry.id
        lanes.update_lane("main", entry.id)
        entries.append(entry)

    manager = MemoryManager(
        storage,
        lanes,
        FakeSummaryClient(),
        tmp_path,
        max_context_tokens=1000,
        reserve_tokens=100,
        keep_recent_tokens=500,
        summary_max_tokens=256,
    )
    result = await manager.compact_if_needed("main")

    assert result is not None
    assert result["status"] == "completed"
    leaf = lanes.get_lane("main").leaf_id
    assert leaf == result["entry_id"]
    context = storage.get_context_entries(leaf)
    assert context[0].entry_type == "compaction"
    assert context[0].metadata["covered_entry_ids"]
    assert context[0].metadata["retained_entry_ids"]
    messages = entries_to_messages(context)
    assert messages[0].role == "system"
    assert messages[0].content.startswith("[会话压缩摘要]")

    reloaded_storage = SessionStorage("memory-test", tmp_path)
    reloaded_lanes = LaneManager("memory-test", tmp_path)
    reloaded_leaf = reloaded_lanes.get_lane("main").leaf_id
    assert reloaded_leaf == leaf
    assert reloaded_storage.get_context_entries(reloaded_leaf)[0].entry_type == "compaction"


@pytest.mark.asyncio
async def test_manual_compaction_can_run_below_threshold(tmp_path: Path):
    storage = SessionStorage("manual-memory-test", tmp_path)
    lanes = LaneManager("manual-memory-test", tmp_path)
    entry = Entry(id="only", role="user", content="保留这条任务目标")
    await storage.append_message(entry)
    lanes.update_lane("main", entry.id)

    manager = MemoryManager(
        storage,
        lanes,
        FakeSummaryClient(),
        tmp_path,
        max_context_tokens=1000,
        keep_recent_tokens=500,
    )
    result = await manager.compact_if_needed("main", force=True, reason="manual")
    assert result["status"] == "noop"
    assert storage.get_entry("only").entry_type == "message"


def test_project_context_loads_instruction_and_memory_files(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("必须运行测试", encoding="utf-8")
    (tmp_path / "CODEMATE.md").write_text("使用中文总结", encoding="utf-8")
    memory_dir = tmp_path / ".codemate"
    memory_dir.mkdir()
    (memory_dir / "memory.md").write_text("当前认证模块正在重构", encoding="utf-8")

    context = load_project_context(tmp_path)

    assert "项目指令: AGENTS.md" in context
    assert "使用中文总结" in context
    assert "当前认证模块正在重构" in context


def test_entry_round_trip_keeps_memory_metadata():
    entry = Entry(
        id="metadata-entry",
        role="assistant",
        content="摘要",
        entry_type="compaction",
        metadata={"covered_entry_ids": ["a"], "tokens_before": 123},
    )
    restored = Entry.from_jsonl_dict(entry.to_jsonl_dict())
    assert restored.entry_type == "compaction"
    assert restored.metadata == entry.metadata
