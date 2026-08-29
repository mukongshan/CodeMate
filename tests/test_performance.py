"""性能和压力测试。"""

import pytest
import asyncio
import time
from pathlib import Path
import tempfile
import shutil

from src.storage.session_storage import SessionStorage
from src.storage.lane_manager import LaneManager
from src.storage.models import Entry
from src.tools.file_tools import ReadFileTool, WriteFileTool
from src.tools.search_tools import GlobTool, GrepTool


class TestPerformance:
    """性能测试。"""

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_bulk_entry_append_performance(self, temp_dir):
        """测试批量追加节点的性能。"""
        storage = SessionStorage("perf-test", temp_dir)

        start = time.perf_counter()

        # 追加 100 个节点
        prev_id = None
        for i in range(100):
            entry = Entry(
                id=f"entry_{i}",
                parent=prev_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}"
            )
            await storage.append_message(entry)
            prev_id = entry.id

        elapsed = time.perf_counter() - start

        # 性能断言
        assert storage.entry_count() == 100
        assert elapsed < 0.5, f"追加 100 个节点耗时 {elapsed:.3f}s，超过 0.5s"

        avg_time = elapsed / 100 * 1000  # ms
        print(f"\n平均每个节点: {avg_time:.2f}ms")

    @pytest.mark.asyncio
    async def test_history_query_performance(self, temp_dir):
        """测试历史查询性能。"""
        storage = SessionStorage("perf-test-2", temp_dir)

        # 创建 100 层深的链
        prev_id = None
        for i in range(100):
            entry = Entry(
                id=f"entry_{i}",
                parent=prev_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}"
            )
            await storage.append_message(entry)
            prev_id = entry.id

        # 测试查询性能
        start = time.perf_counter()

        for _ in range(100):
            path = storage.get_history_path("entry_99")
            assert len(path) == 100

        elapsed = time.perf_counter() - start

        avg_time = elapsed / 100 * 1000  # ms
        assert elapsed < 0.1, f"100 次查询耗时 {elapsed:.3f}s，超过 0.1s"
        print(f"\n平均查询时间: {avg_time:.3f}ms")

    @pytest.mark.asyncio
    async def test_concurrent_append_performance(self, temp_dir):
        """测试并发追加性能。"""
        storage = SessionStorage("perf-test-3", temp_dir)

        # 先创建根节点
        root = Entry(id="root", parent=None, role="user", content="Root")
        await storage.append_message(root)

        async def append_entry(i):
            entry = Entry(
                id=f"entry_{i}",
                parent="root",
                role="assistant",
                content=f"Message {i}"
            )
            await storage.append_message(entry)

        start = time.perf_counter()

        # 并发追加 50 个节点
        await asyncio.gather(*[append_entry(i) for i in range(50)])

        elapsed = time.perf_counter() - start

        assert storage.entry_count() == 51  # root + 50
        print(f"\n并发追加 50 个节点: {elapsed:.3f}s")

    @pytest.mark.asyncio
    async def test_file_operations_performance(self, temp_dir):
        """测试文件操作性能。"""
        workspace = temp_dir / "workspace"
        workspace.mkdir()

        # 创建测试文件
        test_file = workspace / "test.txt"
        test_file.write_text("A" * 1000, encoding="utf-8")  # 1KB

        read_tool = ReadFileTool(workspace)
        write_tool = WriteFileTool(workspace)

        # 测试读取性能
        start = time.perf_counter()
        for _ in range(100):
            await read_tool.execute(path="test.txt")
        read_elapsed = time.perf_counter() - start

        # 测试写入性能
        start = time.perf_counter()
        for i in range(100):
            await write_tool.execute(path=f"output_{i}.txt", content="Test" * 100)
        write_elapsed = time.perf_counter() - start

        print(f"\n读取 100 次 (1KB): {read_elapsed:.3f}s, 平均 {read_elapsed/100*1000:.2f}ms")
        print(f"写入 100 次 (400B): {write_elapsed:.3f}s, 平均 {write_elapsed/100*1000:.2f}ms")

        assert read_elapsed < 1.0, "读取性能不达标"
        assert write_elapsed < 2.0, "写入性能不达标"

    @pytest.mark.asyncio
    async def test_search_performance(self, temp_dir):
        """测试搜索工具性能。"""
        workspace = temp_dir / "workspace"
        workspace.mkdir()

        # 创建 100 个文件
        for i in range(100):
            (workspace / f"file_{i}.txt").write_text(
                f"Content {i}\nLine 2\nLine 3", encoding="utf-8"
            )

        glob_tool = GlobTool(workspace)
        grep_tool = GrepTool(workspace)

        # 测试 Glob 性能
        start = time.perf_counter()
        result = await glob_tool.execute(pattern="*.txt")
        glob_elapsed = time.perf_counter() - start

        assert not result.is_error
        print(f"\nGlob 查找 100 个文件: {glob_elapsed*1000:.2f}ms")

        # 测试 Grep 性能
        start = time.perf_counter()
        result = await grep_tool.execute(pattern="Content", path=str(workspace))
        grep_elapsed = time.perf_counter() - start

        assert not result.is_error
        print(f"Grep 搜索 100 个文件: {grep_elapsed*1000:.2f}ms")

        assert glob_elapsed < 0.5, "Glob 性能不达标"
        assert grep_elapsed < 1.0, "Grep 性能不达标"

    @pytest.mark.asyncio
    async def test_lane_operations_performance(self, temp_dir):
        """测试 Lane 操作性能。"""
        manager = LaneManager("perf-test-4", temp_dir)

        # 测试创建 50 个分支 (使用 kebab-case 命名)
        start = time.perf_counter()
        for i in range(50):
            manager.create_lane(f"branch-{i}", from_id=f"node_{i}")
        create_elapsed = time.perf_counter() - start

        # 测试切换分支
        start = time.perf_counter()
        for i in range(50):
            manager.switch_lane(f"branch-{i}")
        switch_elapsed = time.perf_counter() - start

        print(f"\n创建 50 个分支: {create_elapsed:.3f}s, 平均 {create_elapsed/50*1000:.2f}ms")
        print(f"切换 50 次: {switch_elapsed:.3f}s, 平均 {switch_elapsed/50*1000:.2f}ms")

        assert create_elapsed < 0.5, "创建分支性能不达标"
        assert switch_elapsed < 0.1, "切换分支性能不达标"


class TestStressTest:
    """压力测试。"""

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_large_tree_stress(self, temp_dir):
        """测试大规模树结构。"""
        storage = SessionStorage("stress-test", temp_dir)

        # 创建 1000 个节点的树
        prev_id = None
        for i in range(1000):
            entry = Entry(
                id=f"entry_{i}",
                parent=prev_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}" * 10  # 更长的内容
            )
            await storage.append_message(entry)
            prev_id = entry.id

        assert storage.entry_count() == 1000

        # 测试查询最深节点
        start = time.perf_counter()
        path = storage.get_history_path("entry_999")
        elapsed = time.perf_counter() - start

        assert len(path) == 1000
        print(f"\n查询 1000 层深的路径: {elapsed*1000:.2f}ms")
        assert elapsed < 0.01, "大规模查询性能不达标"

    @pytest.mark.asyncio
    async def test_many_branches_stress(self, temp_dir):
        """测试大量分支。"""
        storage = SessionStorage("stress-test-2", temp_dir)

        # 创建一个根节点
        root = Entry(id="root", parent=None, role="user", content="Root")
        await storage.append_message(root)

        # 创建 100 个分支，每个分支 10 个节点
        for branch_id in range(100):
            parent = "root"
            for depth in range(10):
                entry_id = f"b{branch_id}_d{depth}"
                entry = Entry(
                    id=entry_id,
                    parent=parent,
                    role="assistant",
                    content=f"Branch {branch_id}, Depth {depth}"
                )
                await storage.append_message(entry)
                parent = entry_id

        assert storage.entry_count() == 1001  # root + 100*10

        # 验证根节点有 100 个子节点
        children = storage.get_children("root")
        assert len(children) == 100
        print(f"\n创建 100 个分支，每个 10 层深，共 1001 个节点")

    @pytest.mark.asyncio
    async def test_file_size_stress(self, temp_dir):
        """测试大文件处理。"""
        workspace = temp_dir / "workspace"
        workspace.mkdir()

        read_tool = ReadFileTool(workspace)

        # 创建接近限制的文件 (800KB)
        large_file = workspace / "large.txt"
        large_file.write_text("A" * 800 * 1024, encoding="utf-8")

        start = time.perf_counter()
        result = await read_tool.execute(path="large.txt")
        elapsed = time.perf_counter() - start

        assert not result.is_error
        print(f"\n读取 800KB 文件: {elapsed*1000:.2f}ms")
        assert elapsed < 0.2, "大文件读取性能不达标"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
