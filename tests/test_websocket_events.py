"""测试 WebSocket 事件契约的一致性。"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from src.agent.loop import Agent
from src.agent.providers import EphemeralMessageProvider
from src.llm.events import TextDeltaEvent, DoneEvent
from src.llm.client import LLMClient
from src.tools.registry import ToolRegistry
from src.permission.manager import PermissionManager
from src.storage.lane_manager import LaneManager
from src.storage.session_storage import SessionStorage


class TestWebSocketEvents:
    """测试 WebSocket 事件是否符合文档契约。"""

    @pytest.mark.asyncio
    async def test_status_update_event_fields(self):
        """测试 status_update 事件包含文档规定的字段。"""
        captured_events = []

        async def mock_emit(event: str, payload: dict):
            captured_events.append({"type": event, "data": payload})

        # 创建 Agent
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.model = "test-model"

        async def mock_chat(*args, **kwargs):
            yield TextDeltaEvent(text="Hello")
            yield DoneEvent(stop_reason="stop", usage={"total_tokens": 10})

        mock_llm.chat = mock_chat

        mock_registry = MagicMock(spec=ToolRegistry)
        mock_registry.get_tool_schemas.return_value = []

        from src.permission.manager import PermissionDecision
        mock_permission = MagicMock(spec=PermissionManager)
        mock_permission.check = AsyncMock(return_value=PermissionDecision(allowed=True, reason="test"))

        provider = EphemeralMessageProvider(seed_task="Test")
        agent = Agent(
            session_id="test",
            llm_client=mock_llm,
            tool_registry=mock_registry,
            permission_manager=mock_permission,
            provider=provider,
            workspace=Path("."),
            emit=mock_emit,
        )

        await agent.run("Test message")

        # 查找 status_update 事件
        status_updates = [e for e in captured_events if e["type"] == "status_update"]
        assert len(status_updates) > 0, "应该有 status_update 事件"

        # 验证字段
        for event in status_updates:
            data = event["data"]
            assert "state" in data, "status_update 必须包含 state 字段"
            assert "current_lane" in data, "status_update 必须包含 current_lane 字段"
            assert "current_operation" in data, "status_update 必须包含 current_operation 字段"

    @pytest.mark.asyncio
    async def test_llm_lifecycle_events(self):
        """测试 LLM 请求/响应事件是否被正确记录。"""
        captured_events = []

        async def mock_emit(event: str, payload: dict):
            captured_events.append({"type": event, "data": payload})

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.model = "test-model"
        mock_llm.provider = MagicMock()
        mock_llm.provider.name = "test-provider"

        async def mock_chat(*args, **kwargs):
            yield TextDeltaEvent(text="Test")
            yield DoneEvent(stop_reason="stop", usage={"total_tokens": 20, "completion_tokens": 10})

        mock_llm.chat = mock_chat

        mock_registry = MagicMock(spec=ToolRegistry)
        mock_registry.get_tool_schemas.return_value = []

        from src.permission.manager import PermissionDecision
        mock_permission = MagicMock(spec=PermissionManager)
        mock_permission.check = AsyncMock(return_value=PermissionDecision(allowed=True, reason="test"))

        provider = EphemeralMessageProvider(seed_task="Test")
        agent = Agent(
            session_id="test",
            llm_client=mock_llm,
            tool_registry=mock_registry,
            permission_manager=mock_permission,
            provider=provider,
            workspace=Path("."),
            emit=mock_emit,
        )

        await agent.run("Test")

        event_types = [e["type"] for e in captured_events]

        # 验证必需的日志事件
        assert "context_loaded" in event_types, "应该有 context_loaded 事件"
        assert "llm_request" in event_types, "应该有 llm_request 事件"
        assert "llm_response" in event_types, "应该有 llm_response 事件"

        # 验证 llm_request 字段
        llm_requests = [e for e in captured_events if e["type"] == "llm_request"]
        assert len(llm_requests) > 0
        req_data = llm_requests[0]["data"]
        assert "provider" in req_data
        assert "model" in req_data
        assert "input_tokens" in req_data

        # 验证 llm_response 字段
        llm_responses = [e for e in captured_events if e["type"] == "llm_response"]
        assert len(llm_responses) > 0
        resp_data = llm_responses[0]["data"]
        assert "stop_reason" in resp_data
        assert "output_tokens" in resp_data
        assert "total_tokens" in resp_data

    def test_compare_lanes_includes_identical_field(self, tmp_path):
        """测试 compare_lanes 返回 identical 字段。"""
        storage = SessionStorage("test", tmp_path)
        lane_manager = LaneManager("test", tmp_path)

        # 创建空 session，两个分支应该 identical
        result = lane_manager.compare_lanes("main", "main", storage)

        assert "identical" in result, "compare_lanes 必须返回 identical 字段"
        assert result["identical"] is True, "相同分支应该标记为 identical"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
