from src.agent.prompts import MAIN_SYSTEM_PROMPT


def test_main_prompt_requires_active_subagent_delegation_for_broad_investigation():
    assert "## 子 Agent 调度规则" in MAIN_SYSTEM_PROMPT
    assert "应优先使用" in MAIN_SYSTEM_PROMPT
    assert "跨多个文件、模块或调用方" in MAIN_SYSTEM_PROMPT
    assert "多个主题互不依赖时，在同一轮并行发出多个 `delegate_task` 调用" in MAIN_SYSTEM_PROMPT
    assert "简单的单文件读取" in MAIN_SYSTEM_PROMPT
    assert "需要先搜索才能确定" in MAIN_SYSTEM_PROMPT
