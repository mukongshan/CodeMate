from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agent.state import RunResult
from src.api.session_service import SessionRuntime


class FakeCheckpointManager:
    checkpoint_merge_window_seconds = 300

    def __init__(self, pending: dict):
        self.pending = pending
        self.checkpoint_calls = []

    def defer_run_checkpoint(self, lane, **kwargs):
        return self.pending

    def checkpoint(self, lane, **kwargs):
        self.checkpoint_calls.append((lane, kwargs))
        return SimpleNamespace(
            checkpoint_id="cp-batch",
            commit_sha="abcdef0123456789",
            changed_files=[{"status": "M", "path": "app.py"}],
            run_ids=["run-1", "run-2"],
        )


class NoChangeCheckpointManager(FakeCheckpointManager):
    def defer_run_checkpoint(self, lane, **kwargs):
        return {
            "pending": False,
            "should_flush": False,
            "changed_files": [],
            "pending_run_count": 0,
        }


def make_runtime(manager: FakeCheckpointManager, mode: str = "balanced"):
    runtime = SessionRuntime.__new__(SessionRuntime)
    runtime.config = SimpleNamespace(checkpoint_frequency_mode=mode)
    runtime.git_manager = manager
    runtime.lane_manager = SimpleNamespace(
        current_lane="main",
        get_lane=lambda lane: SimpleNamespace(leaf_id="entry-2"),
    )
    runtime._checkpoint_flush_tasks = {}
    runtime._emit = None
    runtime.state = None
    runtime._active_run_id = None
    return runtime


@pytest.mark.asyncio
async def test_balanced_mode_defers_successful_run_until_flush_boundary():
    manager = FakeCheckpointManager(
        {
            "pending": True,
            "should_flush": False,
            "pending_run_count": 2,
            "changed_files": ["app.py"],
            "next_flush_at": 400,
        }
    )
    runtime = make_runtime(manager)
    scheduled = []
    emitted = []
    runtime._schedule_checkpoint_flush = scheduled.append
    async def emit(event, payload):
        emitted.append((event, payload))

    runtime._emit = emit

    await runtime._handle_completed_run_checkpoint(
        "main", RunResult(run_id="run-2", status="completed")
    )

    assert manager.checkpoint_calls == []
    assert scheduled == ["main"]
    assert emitted[0][0] == "lane_sync_state_changed"
    assert emitted[0][1]["pending_checkpoint"] is True


@pytest.mark.asyncio
async def test_balanced_mode_flushes_when_a_threshold_is_reached():
    manager = FakeCheckpointManager(
        {
            "pending": True,
            "should_flush": True,
            "pending_run_count": 10,
            "changed_files": ["app.py"],
            "flush_reasons": ["max_pending_runs"],
        }
    )
    runtime = make_runtime(manager)
    emitted = []
    async def emit(event, payload):
        emitted.append((event, payload))

    runtime._emit = emit

    await runtime._handle_completed_run_checkpoint(
        "main", RunResult(run_id="run-10", status="completed")
    )

    assert len(manager.checkpoint_calls) == 1
    assert manager.checkpoint_calls[0][1]["reason"] == "run_completed_batch"
    assert emitted[0][0] == "lane_checkpoint_created"


@pytest.mark.asyncio
async def test_manual_mode_keeps_successful_run_dirty_without_scheduling_flush():
    manager = FakeCheckpointManager(
        {
            "pending": True,
            "should_flush": False,
            "pending_run_count": 1,
            "changed_files": ["app.py"],
        }
    )
    runtime = make_runtime(manager, mode="manual")
    emitted = []
    async def emit(event, payload):
        emitted.append((event, payload))

    runtime._emit = emit

    await runtime._handle_completed_run_checkpoint(
        "main", RunResult(run_id="run-1", status="completed")
    )

    assert manager.checkpoint_calls == []
    assert emitted[0][1]["message"] == "代码修改尚未提交，请手动创建检查点"


@pytest.mark.asyncio
async def test_balanced_mode_ignores_successful_run_without_file_changes():
    manager = NoChangeCheckpointManager({})
    runtime = make_runtime(manager)
    scheduled = []
    emitted = []
    runtime._schedule_checkpoint_flush = scheduled.append

    async def emit(event, payload):
        emitted.append((event, payload))

    runtime._emit = emit

    await runtime._handle_completed_run_checkpoint(
        "main", RunResult(run_id="run-1", status="completed")
    )

    assert manager.checkpoint_calls == []
    assert scheduled == []
    assert emitted == []
