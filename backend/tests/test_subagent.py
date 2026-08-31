from types import SimpleNamespace

import pytest

from src.permission.manager import PermissionManager
from src.tools.subagent_tool import DelegateTaskTool


@pytest.mark.asyncio
async def test_subagent_result_uses_soft_length_limit(tmp_path):
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    tool = DelegateTaskTool(
        session_id="test",
        workspace=tmp_path,
        llm_client=None,
        permission_manager=PermissionManager(tmp_path),
        emit=emit,
    )
    result = SimpleNamespace(
        final_text="结论" * 1200,
        status="completed",
        error=None,
        iterations=4,
        touched_paths=["src/example.py"],
        total_tokens=80,
        duration=1.25,
    )

    packaged = await tool._package(result, "sub-1")

    assert len(packaged.content) > 2000
    assert "已截断" not in packaged.content
    assert packaged.metadata["summary_over_limit"] is True
    assert events[-1][0] == "subagent_done"
    assert events[-1][1]["details"]["summary_over_limit"] is True

