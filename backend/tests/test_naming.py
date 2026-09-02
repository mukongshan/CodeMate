from __future__ import annotations

import pytest

from src.intelligence.naming import NamingService
from src.llm.events import DoneEvent, TextDeltaEvent
from src.storage.lane_manager import LaneManager


class FakeLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response

    async def chat(self, messages, tools=None, **kwargs):
        yield TextDeltaEvent(text=self.response)
        yield DoneEvent(stop_reason="stop")


@pytest.mark.asyncio
async def test_session_title_uses_json_response_and_fallbacks() -> None:
    service = NamingService(FakeLLMClient('{"title":"修复登录状态"}'))

    title, source = await service.suggest_session_title("修复登录状态并补充测试")

    assert title == "修复登录状态"
    assert source == "auto"

    fallback_service = NamingService(FakeLLMClient("not-json"))
    title, source = await fallback_service.suggest_session_title("优化缓存命中率")

    assert title == "优化缓存命中率"
    assert source == "fallback"


@pytest.mark.asyncio
async def test_lane_suggestions_filter_invalid_and_existing_names() -> None:
    service = NamingService(
        FakeLLMClient(
            '[{"name":"cache-v2","display_name":"缓存优化","description":"新缓存"},'
            '{"name":"bad name","display_name":"非法","description":"忽略"},'
            '{"name":"main","display_name":"主分支","description":"重复"}]'
        )
    )

    suggestions = await service.suggest_lane_names(
        session_title="缓存优化",
        current_lane="main",
        recent_context=["user: 优化缓存"],
        intent="尝试更激进的缓存策略",
        existing_names=["main", "cache-v1"],
    )

    assert suggestions[0].name == "cache-v2"
    assert len(suggestions) == 3
    assert all(item.name not in {"main", "cache-v1"} for item in suggestions)
    assert all(" " not in item.name for item in suggestions)


def test_lane_display_metadata_roundtrips_and_survives_updates(tmp_path) -> None:
    manager = LaneManager("naming", tmp_path)
    created = manager.create_lane(
        "cache-v1",
        from_id=None,
        description="缓存策略",
        display_name="缓存优化",
        name_source="auto",
    )
    manager.update_lane("cache-v1", "entry-1")

    reloaded = LaneManager("naming", tmp_path)
    pointer = reloaded.get_lane("cache-v1")

    assert created.display_name == "缓存优化"
    assert pointer.display_name == "缓存优化"
    assert pointer.name_source == "auto"
    assert pointer.leaf_id == "entry-1"
