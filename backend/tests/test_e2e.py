"""端到端测试 - 模拟完整的用户场景。"""

import pytest
import asyncio
from pathlib import Path
import tempfile
import shutil

from src.agent.loop import Agent
from src.agent.providers import (
    TreeMessageProvider,
    EphemeralMessageProvider,
    entries_to_messages,
)
from src.storage.session_storage import SessionStorage
from src.storage.lane_manager import LaneManager
from src.storage.models import Entry, ToolUseBlock, ToolResultBlock
from src.tools.registry import ToolRegistry
from src.permission.manager import PermissionManager
from src.llm.client import LLMClient
from src.llm.events import Message, TextDeltaEvent, DoneEvent, ToolCallEvent
from src.config import AppConfig


class MockLLMClient:
    """模拟 LLM 客户端，用于测试。"""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.model = "mock-model"
        self.provider_name = "mock"

    async def chat(self, messages, tools=None, **kwargs):
        """返回预设的响应。"""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1

            for event in response:
                yield event
        else:
            # 默认返回简单响应
            yield TextDeltaEvent(text="OK")
            yield DoneEvent(stop_reason="stop", usage={"total_tokens": 5})


@pytest.fixture
def temp_workspace():
    """创建临时工作目录。"""
    temp = Path(tempfile.mkdtemp())
    # 创建测试文件
    (temp / "test.txt").write_text("Hello World", encoding="utf-8")
    (temp / "data.json").write_text('{"key": "value"}', encoding="utf-8")
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def temp_data_dir():
    """创建临时数据目录。"""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


class TestEndToEndScenarios:
    """端到端场景测试。"""

    @pytest.mark.asyncio
    async def test_simple_file_read_scenario(self, temp_workspace, temp_data_dir):
        """场景1: 读取文件的完整流程。"""
        # 设置存储
        storage = SessionStorage("e2e-test-1", temp_data_dir)
        lane_manager = LaneManager("e2e-test-1", temp_data_dir)

        # 模拟 LLM 响应：调用 read_file 工具
        mock_responses = [
            [
                ToolCallEvent(
                    id="call_1",
                    name="read_file",
                    arguments={"path": str(temp_workspace / "test.txt")}
                ),
                DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 50})
            ],
            [
                TextDeltaEvent(text="文件内容是: Hello World"),
                DoneEvent(stop_reason="stop", usage={"total_tokens": 30})
            ]
        ]

        mock_llm = MockLLMClient(mock_responses)

        # 创建 Agent
        provider = TreeMessageProvider(storage, lane_manager, "main", max_context_tokens=8000)
        registry = ToolRegistry.default(temp_workspace)
        permission = PermissionManager(temp_workspace)

        agent = Agent(
            session_id="e2e-test-1",
            llm_client=mock_llm,
            tool_registry=registry,
            permission_manager=permission,
            provider=provider,
            workspace=temp_workspace
        )

        # 执行
        result = await agent.run("请读取 test.txt 文件")

        # 验证
        assert result.status == "completed"
        assert result.iterations == 2
        assert "Hello World" in result.final_text

        # 验证历史记录
        entries = storage.all_entries()
        assert len(entries) >= 2  # 至少有用户消息和 assistant 响应

    @pytest.mark.asyncio
    async def test_multi_step_workflow(self, temp_workspace, temp_data_dir):
        """场景2: 多步骤工作流。"""
        storage = SessionStorage("e2e-test-2", temp_data_dir)
        lane_manager = LaneManager("e2e-test-2", temp_data_dir)

        # 模拟多步骤：1. glob 查找文件 2. read_file 读取 3. 返回总结
        mock_responses = [
            [
                ToolCallEvent(
                    id="call_1",
                    name="glob",
                    arguments={"pattern": "*.txt"}
                ),
                DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 40})
            ],
            [
                ToolCallEvent(
                    id="call_2",
                    name="read_file",
                    arguments={"path": str(temp_workspace / "test.txt")}
                ),
                DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 40})
            ],
            [
                TextDeltaEvent(text="找到 1 个 txt 文件，内容为 Hello World"),
                DoneEvent(stop_reason="stop", usage={"total_tokens": 30})
            ]
        ]

        mock_llm = MockLLMClient(mock_responses)

        provider = TreeMessageProvider(storage, lane_manager, "main", max_context_tokens=8000)
        registry = ToolRegistry.default(temp_workspace)
        permission = PermissionManager(temp_workspace)

        agent = Agent(
            session_id="e2e-test-2",
            llm_client=mock_llm,
            tool_registry=registry,
            permission_manager=permission,
            provider=provider,
            workspace=temp_workspace
        )

        result = await agent.run("查找所有 txt 文件并读取内容")

        assert result.status == "completed"
        assert result.iterations == 3
        assert result.total_tokens > 0


class TestContextRepair:
    def test_drops_truncated_tool_call_turn(self):
        entries = [
            Entry(
                id="user-1",
                parent=None,
                lane="main",
                seq=1,
                role="user",
                content="请读取文件",
                timestamp=1.0,
            ),
            Entry(
                id="assistant-1",
                parent="user-1",
                lane="main",
                seq=2,
                role="assistant",
                content=[
                    ToolUseBlock(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "demo.txt"},
                    )
                ],
                timestamp=2.0,
            ),
        ]

        messages = entries_to_messages(entries)

        assert [message.role for message in messages] == ["user"]

    def test_keeps_complete_tool_turn(self):
        entries = [
            Entry(
                id="user-1",
                parent=None,
                lane="main",
                seq=1,
                role="user",
                content="请读取文件",
                timestamp=1.0,
            ),
            Entry(
                id="assistant-1",
                parent="user-1",
                lane="main",
                seq=2,
                role="assistant",
                content=[
                    ToolUseBlock(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "demo.txt"},
                    )
                ],
                timestamp=2.0,
            ),
            Entry(
                id="tool-1",
                parent="assistant-1",
                lane="main",
                seq=3,
                role="tool",
                content=[
                    ToolResultBlock(
                        tool_call_id="call_1",
                        content="hello world",
                    )
                ],
                timestamp=3.0,
            ),
        ]

        messages = entries_to_messages(entries)

        assert [message.role for message in messages] == ["user", "assistant", "tool"]
        assert messages[1].tool_calls is not None
        assert messages[1].tool_calls[0].id == "call_1"
        assert messages[2].tool_call_id == "call_1"

    @pytest.mark.asyncio
    async def test_lane_branching_scenario(self, temp_workspace, temp_data_dir):
        """场景3: Lane 分支切换。"""
        storage = SessionStorage("e2e-test-3", temp_data_dir)
        lane_manager = LaneManager("e2e-test-3", temp_data_dir)

        # 在 main 分支执行任务
        mock_llm_1 = MockLLMClient([
            [
                TextDeltaEvent(text="方案 A: 使用缓存"),
                DoneEvent(stop_reason="stop", usage={"total_tokens": 20})
            ]
        ])

        provider_main = TreeMessageProvider(storage, lane_manager, "main", max_context_tokens=8000)
        registry = ToolRegistry.default(temp_workspace)
        permission = PermissionManager(temp_workspace)

        agent_main = Agent(
            session_id="e2e-test-3",
            llm_client=mock_llm_1,
            tool_registry=registry,
            permission_manager=permission,
            provider=provider_main,
            workspace=temp_workspace
        )

        result_main = await agent_main.run("如何优化性能？")
        assert result_main.status == "completed"
        main_leaf = lane_manager.get_lane("main").leaf_id

        # 创建新分支
        lane_manager.create_lane("alternative", from_id=main_leaf, description="尝试另一个方案")
        lane_manager.switch_lane("alternative")

        # 在新分支执行
        mock_llm_2 = MockLLMClient([
            [
                TextDeltaEvent(text="方案 B: 优化算法"),
                DoneEvent(stop_reason="stop", usage={"total_tokens": 20})
            ]
        ])

        provider_alt = TreeMessageProvider(storage, lane_manager, "alternative", max_context_tokens=8000)
        agent_alt = Agent(
            session_id="e2e-test-3",
            llm_client=mock_llm_2,
            tool_registry=registry,
            permission_manager=permission,
            provider=provider_alt,
            workspace=temp_workspace
        )

        result_alt = await agent_alt.run("还有其他方案吗？")
        assert result_alt.status == "completed"

        # 验证两个分支
        assert lane_manager.has_lane("main")
        assert lane_manager.has_lane("alternative")

        # 验证分支对比
        comparison = lane_manager.compare_lanes("main", "alternative", storage)
        assert comparison["common_ancestor"] == main_leaf

    @pytest.mark.asyncio
    async def test_subagent_delegation_scenario(self, temp_workspace, temp_data_dir):
        """场景4: 子 Agent 委托任务。"""
        storage = SessionStorage("e2e-test-4", temp_data_dir)
        lane_manager = LaneManager("e2e-test-4", temp_data_dir)

        # 主 Agent 委托给子 Agent
        mock_responses = [
            [
                ToolCallEvent(
                    id="call_1",
                    name="delegate_task",
                    arguments={"task": "查找所有 Python 文件", "max_steps": 5}
                ),
                DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 50})
            ],
            [
                TextDeltaEvent(text="子 Agent 完成调查"),
                DoneEvent(stop_reason="stop", usage={"total_tokens": 20})
            ]
        ]

        mock_llm = MockLLMClient(mock_responses)

        provider = TreeMessageProvider(storage, lane_manager, "main", max_context_tokens=8000)
        registry = ToolRegistry.default(temp_workspace)
        permission = PermissionManager(temp_workspace)

        # 注册子 Agent 工具
        from src.tools.subagent_tool import DelegateTaskTool
        delegate_tool = DelegateTaskTool(
            session_id="e2e-test-4",
            workspace=temp_workspace,
            llm_client=mock_llm,
            permission_manager=permission,
            depth=0,
            emit=None
        )
        registry.register(delegate_tool)

        agent = Agent(
            session_id="e2e-test-4",
            llm_client=mock_llm,
            tool_registry=registry,
            permission_manager=permission,
            provider=provider,
            workspace=temp_workspace
        )

        result = await agent.run("帮我调查项目结构")

        # 验证结果
        assert result.status in ["completed", "partial"]
        assert result.iterations >= 1


class TestErrorRecovery:
    """错误恢复场景测试。"""

    @pytest.mark.asyncio
    async def test_tool_error_recovery(self, temp_workspace, temp_data_dir):
        """测试工具执行失败后的恢复。"""
        storage = SessionStorage("e2e-test-5", temp_data_dir)
        lane_manager = LaneManager("e2e-test-5", temp_data_dir)

        # 模拟：1. 尝试读取不存在的文件（失败）2. LLM 修正 3. 成功
        mock_responses = [
            [
                ToolCallEvent(
                    id="call_1",
                    name="read_file",
                    arguments={"path": str(temp_workspace / "nonexistent.txt")}
                ),
                DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 40})
            ],
            [
                TextDeltaEvent(text="文件不存在，让我读取 test.txt"),
                ToolCallEvent(
                    id="call_2",
                    name="read_file",
                    arguments={"path": str(temp_workspace / "test.txt")}
                ),
                DoneEvent(stop_reason="tool_calls", usage={"total_tokens": 50})
            ],
            [
                TextDeltaEvent(text="成功读取到内容"),
                DoneEvent(stop_reason="stop", usage={"total_tokens": 20})
            ]
        ]

        mock_llm = MockLLMClient(mock_responses)

        provider = TreeMessageProvider(storage, lane_manager, "main", max_context_tokens=8000)
        registry = ToolRegistry.default(temp_workspace)
        permission = PermissionManager(temp_workspace)

        agent = Agent(
            session_id="e2e-test-5",
            llm_client=mock_llm,
            tool_registry=registry,
            permission_manager=permission,
            provider=provider,
            workspace=temp_workspace
        )

        result = await agent.run("读取文件")

        # 验证 Agent 能够从错误中恢复
        assert result.status == "completed"
        assert result.iterations == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
