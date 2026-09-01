"""测试 Agent 主循环。"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from src.agent.loop import Agent
from src.agent.providers import EphemeralMessageProvider
from src.llm.events import Message, TextDeltaEvent, DoneEvent, ToolCallEvent
from src.llm.client import LLMClient
from src.tools.base import ToolResult
from src.tools.registry import ToolRegistry
from src.permission.manager import PermissionManager


class TestAgentLoop:
    """测试 Agent 执行循环。"""

    @pytest.fixture
    def mock_llm_client(self):
        """模拟 LLM 客户端。"""
        client = MagicMock(spec=LLMClient)
        client.model = "test-model"
        return client

    @pytest.fixture
    def mock_registry(self):
        """模拟工具注册表。

        execute 必须返回真实的 ToolResult：它的 content 会作为 tool 消息回灌
        进上下文，如果留成默认的 MagicMock，下一轮 _build_messages 就会拿到
        非字符串的 content。
        """
        registry = MagicMock(spec=ToolRegistry)
        registry.get_tool_schemas.return_value = []
        registry.execute = AsyncMock(return_value=ToolResult.ok("mock tool output"))
        return registry

    @pytest.fixture
    def mock_permission(self):
        """模拟权限管理器。"""
        from src.permission.manager import PermissionDecision
        perm = MagicMock(spec=PermissionManager)
        perm.check = AsyncMock(return_value=PermissionDecision(allowed=True, reason="test"))
        return perm

    @pytest.fixture
    def agent(self, mock_llm_client, mock_registry, mock_permission):
        """创建测试 Agent。"""
        provider = EphemeralMessageProvider(seed_task="Test task")

        agent = Agent(
            session_id="test",
            llm_client=mock_llm_client,
            tool_registry=mock_registry,
            permission_manager=mock_permission,
            provider=provider,
            workspace=Path("."),
        )
        return agent

    @pytest.mark.asyncio
    async def test_simple_text_response(self, agent, mock_llm_client):
        """测试简单文本响应（无工具调用）。"""
        # 模拟 LLM 返回纯文本
        async def mock_chat(*args, **kwargs):
            yield TextDeltaEvent(text="Hello")
            yield TextDeltaEvent(text=" world")
            yield DoneEvent(stop_reason="stop", usage={"total_tokens": 10})

        mock_llm_client.chat = mock_chat

        result = await agent.run("Say hello")

        assert result.status == "completed"
        assert result.final_text == "Hello world"
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_empty_response_is_reported_as_error(self, agent, mock_llm_client):
        """模型空回复不能被当成成功，也不应写入空 assistant 节点。"""
        async def mock_chat(*args, **kwargs):
            yield DoneEvent(stop_reason="stop", usage={"total_tokens": 1})

        mock_llm_client.chat = mock_chat

        result = await agent.run("请修改文件")

        assert result.status == "error"
        assert result.error == "模型返回了空回复，未执行任何工具操作"
        assert not any(
            message.role == "assistant" and not message.content
            for message in agent.provider.get_context()
        )

    @pytest.mark.asyncio
    async def test_empty_response_retries_with_explicit_continuation_prompt(
        self, agent, mock_llm_client
    ):
        calls = []

        async def mock_chat(messages, *args, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                yield DoneEvent(stop_reason="stop", usage={"total_tokens": 1})
                return
            yield TextDeltaEvent(text="已继续完成")
            yield DoneEvent(stop_reason="stop", usage={"total_tokens": 2})

        mock_llm_client.chat = mock_chat

        result = await agent.run("请修改文件")

        assert result.status == "completed"
        assert result.final_text == "已继续完成"
        assert len(calls) == 2
        assert calls[1][-1].role == "user"
        assert "立即调用合适的文件编辑工具" in (calls[1][-1].content or "")

    @pytest.mark.asyncio
    async def test_max_iterations(self, agent, mock_llm_client):
        """测试达到最大迭代次数。"""
        # 模拟 LLM 一直要求调用工具
        async def mock_chat(*args, **kwargs):
            yield ToolCallEvent(id="call1", name="read_file", arguments={"path": "test.txt"})
            yield DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 10})

        mock_llm_client.chat = mock_chat

        result = await agent.run("Test", max_steps=3)

        assert result.status == "partial"
        assert result.iterations == 3
        assert "达到最大迭代次数" in result.error

    @pytest.mark.asyncio
    async def test_interrupt_preserves_partial_response(
        self, mock_llm_client, mock_registry, mock_permission
    ):
        stream_blocked = asyncio.Event()
        captured_events = []

        async def mock_chat(*args, **kwargs):
            yield TextDeltaEvent(text="已经生成的部分回复")
            stream_blocked.set()
            await asyncio.Event().wait()

        async def emit(event, payload):
            captured_events.append((event, payload))

        mock_llm_client.chat = mock_chat
        provider = EphemeralMessageProvider(seed_task="Test task")
        agent = Agent(
            session_id="test",
            llm_client=mock_llm_client,
            tool_registry=mock_registry,
            permission_manager=mock_permission,
            provider=provider,
            workspace=Path("."),
            emit=emit,
        )

        task = asyncio.create_task(agent.run("请回答"))
        await stream_blocked.wait()
        task.cancel()
        result = await task

        assert result.status == "aborted"
        assert any(
            message.role == "assistant" and message.content == "已经生成的部分回复"
            for message in provider.get_context()
        )
        completed = [payload for event, payload in captured_events if event == "run_completed"]
        assert len(completed) == 1
        assert completed[0]["status"] == "aborted"
        assert any(
            event == "message_end" and payload["stop_reason"] == "interrupted"
            for event, payload in captured_events
        )

    @pytest.mark.asyncio
    async def test_interrupt_closes_pending_tool_calls(
        self, mock_llm_client, mock_registry, mock_permission
    ):
        tool_started = asyncio.Event()

        async def mock_chat(*args, **kwargs):
            yield ToolCallEvent(
                id="call-interrupt",
                name="read_file",
                arguments={"path": "test.txt"},
            )
            yield DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 10})

        async def blocking_execute(*args, **kwargs):
            tool_started.set()
            await asyncio.Event().wait()

        mock_llm_client.chat = mock_chat
        mock_registry.get_tool_schemas.return_value = [{"type": "function"}]
        mock_registry.execute = blocking_execute
        provider = EphemeralMessageProvider(seed_task="Test task")
        agent = Agent(
            session_id="test",
            llm_client=mock_llm_client,
            tool_registry=mock_registry,
            permission_manager=mock_permission,
            provider=provider,
            workspace=Path("."),
        )

        task = asyncio.create_task(agent.run("请读取文件"))
        await tool_started.wait()
        task.cancel()
        result = await task

        assert result.status == "aborted"
        tool_messages = [
            message for message in provider.get_context() if message.role == "tool"
        ]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call-interrupt"
        assert "用户已中断" in (tool_messages[0].content or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
