"""测试 LLM 协议字段和流式工具调用恢复。"""

from src.agent.providers import entry_to_message
from src.llm.events import Message
from src.llm.stream_buffer import StreamBuffer
from src.storage.models import Entry


def test_message_reasoning_content_is_provider_selectable():
    message = Message(
        role="assistant",
        content=None,
        reasoning_content="先检查文件结构",
    )

    assert message.to_api_dict()["reasoning_content"] == "先检查文件结构"
    assert "reasoning_content" not in message.to_api_dict(
        include_reasoning_content=False
    )


def test_reasoning_content_round_trips_through_entry():
    entry = Entry(
        role="assistant",
        content="",
        reasoning_content="需要继续调用工具",
    )

    restored = Entry.from_jsonl_dict(entry.to_jsonl_dict())
    message = entry_to_message(restored)

    assert message.reasoning_content == "需要继续调用工具"


def test_stream_buffer_reports_incomplete_tool_call():
    buffer = StreamBuffer()
    buffer.add_tool_call_delta(
        index=0,
        call_id="call-1",
        name="write_file",
        arguments='{"path":"a.txt"',
    )

    assert buffer.has_incomplete_tool_calls()
    assert buffer.get_complete_tool_calls() == []


def test_stream_buffer_accepts_complete_empty_arguments():
    buffer = StreamBuffer()
    buffer.add_tool_call_delta(
        index=0,
        call_id="call-1",
        name="read_file",
        arguments="",
    )

    assert not buffer.has_incomplete_tool_calls()
    assert buffer.get_complete_tool_calls()[0]["arguments"] == {}
