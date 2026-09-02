"""为 Session 和 Lane 提供可失败降级的命名能力。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from ..llm.client import LLMClient
from ..llm.events import DoneEvent, Message, TextDeltaEvent

LANE_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LANE_NAME_MAX_LENGTH = 64
TITLE_MAX_LENGTH = 80
DISPLAY_NAME_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 240


@dataclass(frozen=True)
class LaneNameSuggestion:
    name: str
    display_name: str
    description: str
    source: str = "auto"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "source": self.source,
        }


class NamingService:
    """调用无工具 LLM，并在任何异常下返回本地结果。"""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def suggest_session_title(
        self, user_message: str, final_text: str = ""
    ) -> tuple[str, str]:
        fallback = self.fallback_session_title(user_message)
        if not user_message.strip():
            return fallback, "fallback"
        prompt = (
            "请为一次编程任务生成简洁的中文会话标题。只返回 JSON 对象，格式为 "
            '{"title":"..."}，不要 Markdown、解释或换行。标题应概括任务目标，'
            f"不超过 {TITLE_MAX_LENGTH} 个字符。\\n\\n"
            f"用户需求：{user_message[:2000]}\\n\\n"
            f"最终回复摘要：{final_text[:1200]}"
        )
        try:
            payload = await self._request_json(prompt)
            title = self._clean_text(payload.get("title"), TITLE_MAX_LENGTH)
            if title:
                return title, "auto"
        except Exception:
            pass
        return fallback, "fallback"

    async def suggest_lane_names(
        self,
        session_title: str,
        current_lane: str,
        recent_context: Iterable[str],
        intent: str,
        existing_names: Iterable[str],
    ) -> list[LaneNameSuggestion]:
        existing = {name.strip().lower() for name in existing_names if name.strip()}
        context = "\\n".join(item[:400] for item in recent_context if item.strip())
        prompt = (
            "请为编程 Agent 的新 Lane 生成最多 3 个方案候选。只返回 JSON 数组，"
            '每项格式为 {"name":"safe-slug","display_name":"中文名",'
            '"description":"目标"}，不要 Markdown 或额外解释。name 必须是小写 '
            "kebab-case，只能包含字母、数字和单个短横线；候选应彼此不同。\\n\\n"
            f"Session 标题：{session_title[:TITLE_MAX_LENGTH]}\\n"
            f"当前 Lane：{current_lane}\\n"
            f"新方案意图：{intent[:1000]}\\n"
            f"最近上下文：{context[:2400]}"
        )
        candidates: list[LaneNameSuggestion] = []
        try:
            payload = await self._request_json(prompt)
            raw_items = payload if isinstance(payload, list) else payload.get("suggestions", [])
            if isinstance(raw_items, list):
                candidates = self._normalize_lane_suggestions(raw_items, existing)
        except Exception:
            candidates = []

        fallback_seed = intent or session_title or current_lane or "task"
        fallbacks = self._fallback_lane_suggestions(fallback_seed, existing)
        for candidate in fallbacks:
            if len(candidates) >= 3:
                break
            if candidate.name not in {item.name for item in candidates}:
                candidates.append(candidate)
        return candidates[:3]

    async def _request_json(self, prompt: str) -> Any:
        messages = [
            Message(
                role="system",
                content="你是一个只负责命名的辅助服务，不执行工具，不修改代码。",
            ),
            Message(role="user", content=prompt),
        ]
        parts: list[str] = []
        async for event in self.llm_client.chat(
            messages, tools=None, max_tokens=220, temperature=0.2
        ):
            if isinstance(event, TextDeltaEvent):
                parts.append(event.text)
            elif isinstance(event, DoneEvent):
                break
        text = "".join(parts).strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\\s*|\\s*```$", "", text, flags=re.IGNORECASE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            object_match = re.search(r"(\\{.*\\}|\\[.*\\])", text, flags=re.DOTALL)
            if object_match is None:
                raise
            return json.loads(object_match.group(1))

    def _normalize_lane_suggestions(
        self, raw_items: list[Any], existing: set[str]
    ) -> list[LaneNameSuggestion]:
        result: list[LaneNameSuggestion] = []
        seen = set(existing)
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = self._clean_slug(item.get("name"))
            if not name or name in seen:
                continue
            display_name = self._clean_text(item.get("display_name"), DISPLAY_NAME_MAX_LENGTH) or name
            description = self._clean_text(item.get("description"), DESCRIPTION_MAX_LENGTH)
            result.append(LaneNameSuggestion(name, display_name, description))
            seen.add(name)
            if len(result) == 3:
                break
        return result

    def _fallback_lane_suggestions(
        self, seed: str, existing: set[str]
    ) -> list[LaneNameSuggestion]:
        digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:6]
        bases = [("explore", "探索方案"), ("alternative", "备选方案"), ("verify", "验证方案")]
        result: list[LaneNameSuggestion] = []
        for base, display_name in bases:
            name = f"{base}-{digest}"
            if name in existing:
                continue
            result.append(LaneNameSuggestion(name, display_name, "由本地规则生成的可编辑候选", "fallback"))
        return result

    @staticmethod
    def _clean_text(value: Any, max_length: int) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.replace("\\r", " ").replace("\\n", " ").split())[:max_length].strip()

    @staticmethod
    def _clean_slug(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        value = value.strip().lower()
        if len(value) > LANE_NAME_MAX_LENGTH or not LANE_NAME_PATTERN.fullmatch(value):
            return ""
        return value

    @staticmethod
    def fallback_session_title(user_message: str) -> str:
        first_line = user_message.strip().splitlines()[0] if user_message.strip() else "未命名会话"
        title = " ".join(first_line.split())
        return title[:TITLE_MAX_LENGTH].strip() or "未命名会话"
