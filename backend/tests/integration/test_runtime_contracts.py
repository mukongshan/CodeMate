from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.session_service import SessionRuntime
from src.api.ws import _handle_message
from src.agent.providers import Message, TreeMessageProvider
from src.storage.lane_manager import LaneManager
from src.storage.session_storage import SessionStorage
from src.tools.exec_tool import BashTool


class FakeRuntime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.run_count = 0
        self.interrupt_count = 0

    async def emit(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))

    async def run(self, content: str, lane: str | None = None):
        self.run_count += 1
        await self.emit(
            "run_completed",
            {
                "run_id": "run-1",
                "status": "completed",
                "iterations": 1,
                "total_tokens": 8,
                "duration": 0.1,
            },
        )
        return SimpleNamespace(
            run_id="run-1",
            status="completed",
            iterations=1,
            total_tokens=8,
            duration=0.1,
        )

    def resolve_permission(self, request_id: str, action: str) -> bool:
        return False

    async def interrupt_run(self, run_id: str | None = None) -> bool:
        self.interrupt_count += 1
        return True


class TestWebSocketContracts:
    @pytest.mark.asyncio
    async def test_send_message_emits_run_completed_once(self):
        runtime = FakeRuntime()

        task = await _handle_message(
            runtime, {"type": "send_message", "content": "hello"}
        )
        assert task is not None
        await task

        run_completed = [event for event, _ in runtime.events if event == "run_completed"]
        assert runtime.run_count == 1
        assert len(run_completed) == 1

    @pytest.mark.asyncio
    async def test_interrupt_message_targets_current_run(self):
        runtime = FakeRuntime()

        task = await _handle_message(runtime, {"type": "interrupt_run"})

        assert task is None
        assert runtime.interrupt_count == 1

    @pytest.mark.asyncio
    async def test_runtime_interrupt_cancels_active_task_once(self):
        runtime = SessionRuntime.__new__(SessionRuntime)
        events = []
        permission_failures = []

        async def emit(event, payload):
            events.append((event, payload))

        async def wait_forever():
            await asyncio.Event().wait()

        active_task = asyncio.create_task(wait_forever())
        runtime._active_run_task = active_task
        runtime._active_run_id = "run-1"
        runtime._interrupt_requested = False
        runtime.emit = emit
        runtime.fail_pending_permissions = permission_failures.append

        accepted = await runtime.interrupt_run("run-1")
        duplicate = await runtime.interrupt_run("run-1")

        assert accepted is True
        assert duplicate is False
        assert permission_failures == ["用户已中断当前运行"]
        assert events == [
            ("run_interrupt_requested", {"run_id": "run-1", "status": "interrupting"})
        ]
        with pytest.raises(asyncio.CancelledError, match="用户中断"):
            await active_task


class TestBashToolContracts:
    @pytest.mark.asyncio
    async def test_builtin_commands_work_in_wsl_bash(self, tmp_path):
        tool = BashTool(tmp_path)
        marker = tmp_path / "marker.txt"
        marker.write_text("marker", encoding="utf-8")

        result = await tool.execute(command="echo hello")
        listing = await tool.execute(command="ls")

        assert not result.is_error
        assert "hello" in result.content.lower()
        assert not listing.is_error
        assert "marker.txt" in listing.content.lower()

    @pytest.mark.asyncio
    async def test_shell_chaining_runs_in_wsl_bash(self, tmp_path):
        tool = BashTool(tmp_path)
        result = await tool.execute(command="echo one && echo two")

        assert not result.is_error
        assert "one" in result.content.lower()
        assert "two" in result.content.lower()


class TestTreeLaneContracts:
    @pytest.mark.asyncio
    async def test_tree_lane_recovery_and_compare_survive_reload(self, tmp_path):
        session_id = "integration-session"
        storage = SessionStorage(session_id, tmp_path)
        lane_manager = LaneManager(session_id, tmp_path)

        provider_main = TreeMessageProvider(
            storage, lane_manager, "main", max_context_tokens=8000
        )
        root_id = await provider_main.append(Message(role="user", content="root"))
        assistant_id = await provider_main.append(
            Message(role="assistant", content="main answer")
        )

        lane_manager.create_lane("feature-x", from_id=assistant_id, description="branch")
        lane_manager.switch_lane("feature-x")

        provider_branch = TreeMessageProvider(
            storage, lane_manager, "feature-x", max_context_tokens=8000
        )
        branch_id = await provider_branch.append(
            Message(role="user", content="branch answer")
        )

        storage_reloaded = SessionStorage(session_id, tmp_path)
        lane_manager_reloaded = LaneManager(session_id, tmp_path)

        assert lane_manager_reloaded.current_lane == "feature-x"
        assert lane_manager_reloaded.get_lane("feature-x").leaf_id == branch_id
        assert lane_manager_reloaded.get_lane("main").leaf_id == assistant_id

        history = storage_reloaded.get_history_path(branch_id)
        assert [entry.id for entry in history] == [root_id, assistant_id, branch_id]

        comparison = lane_manager_reloaded.compare_lanes(
            "main", "feature-x", storage_reloaded
        )
        assert comparison["common_ancestor"] == assistant_id
        assert not comparison["identical"]
        assert comparison["lane_a_diff"] == []
        assert comparison["lane_b_diff"] == [branch_id]
