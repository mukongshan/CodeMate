"""基础功能测试。

运行：pytest tests/test_basic.py -v
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from src.storage.models import Entry, LanePointer
from src.storage.session_storage import SessionStorage
from src.storage.lane_manager import LaneManager
from src.config import AppConfig


class TestSessionStorage:
    """测试树形历史存储。"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时测试目录。"""
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def storage(self, temp_dir):
        """创建测试用的 SessionStorage。"""
        return SessionStorage("test_session", temp_dir)

    def test_create_and_load(self, storage):
        """测试创建和加载。"""
        assert storage.session_id == "test_session"
        assert storage.entry_count() == 0

    @pytest.mark.asyncio
    async def test_append_entry(self, storage):
        """测试追加节点。"""
        entry1 = Entry(id="entry1", parent=None, role="user", content="Hello")
        result = await storage.append_message(entry1)

        assert result.seq == 1
        assert storage.entry_count() == 1

        loaded = storage.get_entry("entry1")
        assert loaded is not None
        assert loaded.content == "Hello"

    @pytest.mark.asyncio
    async def test_parent_chain(self, storage):
        """测试 parent 链。"""
        entry1 = Entry(id="e1", parent=None, role="user", content="Q1")
        entry2 = Entry(id="e2", parent="e1", role="assistant", content="A1")
        entry3 = Entry(id="e3", parent="e2", role="user", content="Q2")

        await storage.append_message(entry1)
        await storage.append_message(entry2)
        await storage.append_message(entry3)

        path = storage.get_history_path("e3")
        assert len(path) == 3
        assert [e.id for e in path] == ["e1", "e2", "e3"]

    @pytest.mark.asyncio
    async def test_fork(self, storage):
        """测试分叉。"""
        # 主干
        entry1 = Entry(id="e1", parent=None, role="user", content="Q1")
        entry2 = Entry(id="e2", parent="e1", role="assistant", content="A1")

        # 两个分叉
        entry3a = Entry(id="e3a", parent="e2", role="user", content="Branch A")
        entry3b = Entry(id="e3b", parent="e2", role="user", content="Branch B")

        await storage.append_message(entry1)
        await storage.append_message(entry2)
        await storage.append_message(entry3a)
        await storage.append_message(entry3b)

        children = storage.get_children("e2")
        assert len(children) == 2
        assert set(children) == {"e3a", "e3b"}
        assert storage.is_fork_point("e2")

    @pytest.mark.asyncio
    async def test_common_ancestor(self, storage):
        """测试最近公共祖先查询。"""
        # 创建树：root -> e1 -> e2 -> e3a
        #                    \-> e3b
        root = Entry(id="root", parent=None, role="user", content="Root")
        e1 = Entry(id="e1", parent="root", role="assistant", content="E1")
        e2 = Entry(id="e2", parent="e1", role="user", content="E2")
        e3a = Entry(id="e3a", parent="e2", role="assistant", content="E3a")
        e3b = Entry(id="e3b", parent="e2", role="assistant", content="E3b")

        for entry in [root, e1, e2, e3a, e3b]:
            await storage.append_message(entry)

        ancestor = storage.find_common_ancestor("e3a", "e3b")
        assert ancestor == "e2"


class TestLaneManager:
    """测试 Lane 分支管理。"""

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def manager(self, temp_dir):
        return LaneManager("test_session", temp_dir)

    def test_default_main_lane(self, manager):
        """测试默认 main 分支。"""
        assert manager.has_lane("main")
        main = manager.get_lane("main")
        assert main.lane == "main"
        assert main.leaf_id is None  # 空树时指针为 None

    def test_create_lane(self, manager):
        """测试创建新分支。"""
        pointer = manager.create_lane("feature-1", from_id="node123", description="Feature 1")
        assert pointer.lane == "feature-1"
        assert pointer.leaf_id == "node123"
        assert pointer.created_from == "node123"

    def test_update_lane(self, manager):
        """测试更新分支指针。"""
        manager.create_lane("test-lane", from_id="n1")
        updated = manager.update_lane("test-lane", leaf_id="n2")

        assert updated.leaf_id == "n2"
        assert updated.seq == 2

    def test_switch_lane(self, manager):
        """测试切换活跃分支。"""
        manager.create_lane("lane-a", from_id="n1")
        manager.switch_lane("lane-a")

        assert manager.current_lane == "lane-a"

    def test_delete_lane(self, manager):
        """测试删除分支。"""
        manager.create_lane("temp-lane", from_id="n1")
        assert manager.has_lane("temp-lane")

        manager.delete_lane("temp-lane")
        assert not manager.has_lane("temp-lane")

    def test_cannot_delete_main(self, manager):
        """测试不能删除 main 分支。"""
        with pytest.raises(Exception):
            manager.delete_lane("main")

    def test_cannot_delete_current_lane(self, manager):
        """测试不能删除当前活跃分支。"""
        manager.create_lane("active", from_id="n1")
        manager.switch_lane("active")

        with pytest.raises(Exception):
            manager.delete_lane("active")


class TestConfig:
    """测试配置加载。"""

    def test_from_env_defaults(self, monkeypatch):
        """测试默认配置。"""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        config = AppConfig.from_env()

        assert config.llm.provider == "deepseek"
        assert config.max_iterations == 20
        assert config.host == "127.0.0.1"
        assert config.port == 8000

    def test_from_env_with_api_key(self, monkeypatch):
        """测试从环境变量加载 API Key。"""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-12345")

        config = AppConfig.from_env()

        assert config.llm.provider == "deepseek"
        assert config.llm.api_key == "test-key-12345"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
