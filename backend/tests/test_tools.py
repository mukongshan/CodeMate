"""完整的工具系统测试。"""

import pytest
from pathlib import Path
import tempfile
import shutil

from src.tools.base import ToolResult
from src.tools.file_tools import ReadFileTool, WriteFileTool, EditFileTool
from src.tools.search_tools import GlobTool, GrepTool
from src.tools.exec_tool import BashTool


class TestFileTools:
    """测试文件操作工具。"""

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def sample_file(self, temp_dir):
        """创建测试文件。"""
        file_path = temp_dir / "test.txt"
        file_path.write_text("Hello World\nLine 2\nLine 3", encoding="utf-8")
        return file_path

    @pytest.mark.asyncio
    async def test_read_file(self, temp_dir, sample_file):
        """测试读取文件。"""
        tool = ReadFileTool(temp_dir)
        result = await tool.execute(path=str(sample_file))

        assert not result.is_error
        assert "Hello World" in result.content
        assert "Line 2" in result.content

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, temp_dir):
        """测试读取不存在的文件。"""
        tool = ReadFileTool(temp_dir)
        result = await tool.execute(path=str(temp_dir / "nonexistent.txt"))

        assert result.is_error
        assert "不存在" in result.content or "找不到" in result.content

    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir):
        """测试写入文件。"""
        tool = WriteFileTool(temp_dir)
        target = temp_dir / "output.txt"

        result = await tool.execute(path=str(target), content="Test content")

        assert not result.is_error
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Test content"
        assert result.metadata["file_change"]["path"] == "output.txt"
        assert result.metadata["file_change"]["added_lines"] == 1
        assert result.metadata["file_change"]["removed_lines"] == 0

    @pytest.mark.asyncio
    async def test_write_file_creates_directory(self, temp_dir):
        """测试写入文件时自动创建目录。"""
        tool = WriteFileTool(temp_dir)
        target = temp_dir / "subdir" / "output.txt"

        result = await tool.execute(path=str(target), content="Test")

        assert not result.is_error
        assert target.exists()

    @pytest.mark.asyncio
    async def test_edit_file(self, temp_dir, sample_file):
        """测试编辑文件。"""
        tool = EditFileTool(temp_dir)

        result = await tool.execute(
            path=str(sample_file),
            old_string="Hello World",
            new_string="Hello Python"
        )

        assert not result.is_error
        content = sample_file.read_text(encoding="utf-8")
        assert "Hello Python" in content
        assert "Hello World" not in content
        assert result.metadata["file_change"]["added_lines"] == 1
        assert result.metadata["file_change"]["removed_lines"] == 1
        assert "-Hello World" in result.metadata["file_change"]["diff"]
        assert "+Hello Python" in result.metadata["file_change"]["diff"]

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, temp_dir, sample_file):
        """测试编辑时找不到目标文本。"""
        tool = EditFileTool(temp_dir)

        result = await tool.execute(
            path=str(sample_file),
            old_string="NonExistent",
            new_string="NewText"
        )

        assert result.is_error
        # Check that the error message indicates the text was not found
        assert "未找到" in result.content or "未在" in result.content


class TestSearchTools:
    """测试搜索工具。"""

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        # 创建测试文件结构
        (temp / "file1.py").write_text("def hello():\n    print('hello')", encoding="utf-8")
        (temp / "file2.py").write_text("def world():\n    print('world')", encoding="utf-8")
        (temp / "data.txt").write_text("some data", encoding="utf-8")
        (temp / "subdir").mkdir()
        (temp / "subdir" / "nested.py").write_text("nested file", encoding="utf-8")
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_glob_all_files(self, temp_dir):
        """测试 glob 查找所有文件。"""
        tool = GlobTool(temp_dir)
        result = await tool.execute(pattern="**/*.py")

        assert not result.is_error
        assert "file1.py" in result.content
        assert "file2.py" in result.content
        assert "nested.py" in result.content

    @pytest.mark.asyncio
    async def test_glob_with_limit(self, temp_dir):
        """测试 glob 限制结果数量。"""
        tool = GlobTool(temp_dir)
        result = await tool.execute(pattern="*.py", limit=1)

        assert not result.is_error
        # 应该只返回一个文件
        lines = [l for l in result.content.split('\n') if l.strip()]
        assert len(lines) <= 2  # 可能有标题行

    @pytest.mark.asyncio
    async def test_grep_simple(self, temp_dir):
        """测试 grep 简单搜索。"""
        tool = GrepTool(temp_dir)
        result = await tool.execute(pattern="hello", path=str(temp_dir))

        assert not result.is_error
        assert "hello" in result.content.lower()
        assert "file1.py" in result.content

    @pytest.mark.asyncio
    async def test_grep_with_context(self, temp_dir):
        """测试 grep 带上下文。"""
        tool = GrepTool(temp_dir)
        result = await tool.execute(pattern="def", path=str(temp_dir), context=1)

        assert not result.is_error
        assert "def" in result.content


class TestBashTool:
    """测试命令执行工具。"""

    @pytest.fixture
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_simple_command(self, temp_dir):
        """测试简单命令执行。"""
        tool = BashTool(temp_dir)
        result = await tool.execute(command="echo hello")

        assert not result.is_error
        assert "hello" in result.content.lower()
        assert "[stderr]" not in result.content

    @pytest.mark.asyncio
    async def test_missing_workspace_is_created(self, temp_dir):
        """测试缺失的 workspace 会先创建，再进入 WSL 执行。"""
        workspace = temp_dir / "missing-workspace"

        tool = BashTool(workspace)
        result = await tool.execute(command="pwd")

        assert workspace.exists()
        assert not result.is_error
        assert "missing-workspace" in result.content
        assert "[stderr]" not in result.content

    @pytest.mark.asyncio
    async def test_list_directory(self, temp_dir):
        """测试列出目录。"""
        # 创建测试文件
        (temp_dir / "test.txt").write_text("test", encoding="utf-8")

        tool = BashTool(temp_dir)
        result = await tool.execute(command="ls")

        assert not result.is_error
        assert "test.txt" in result.content

    @pytest.mark.asyncio
    async def test_command_timeout(self, temp_dir):
        """测试命令超时。"""
        tool = BashTool(temp_dir)
        result = await tool.execute(command="sleep 10", timeout=1)

        assert result.is_error
        assert result.metadata["timed_out"] is True

    @pytest.mark.asyncio
    async def test_shell_syntax_runs_in_wsl(self, temp_dir):
        """测试 WSL bash 支持 shell 语法。"""
        tool = BashTool(temp_dir)
        result = await tool.execute(
            command="printf 'hello\\nworld\\n' | grep world > marker.txt && cat marker.txt"
        )

        assert not result.is_error
        assert "world" in result.content
        assert (temp_dir / "marker.txt").read_text(encoding="utf-8").strip() == "world"

    @pytest.mark.asyncio
    async def test_command_failure(self, temp_dir):
        """测试命令执行失败。"""
        tool = BashTool(temp_dir)
        result = await tool.execute(command="nonexistent_command_12345")

        assert result.is_error

    @pytest.mark.asyncio
    async def test_command_stderr_is_preserved(self, temp_dir):
        """测试真实命令 stderr 不会被 WSL 启动提示过滤吞掉。"""
        tool = BashTool(temp_dir)
        result = await tool.execute(command="echo real-error >&2; false")

        assert result.is_error
        assert "real-error" in result.content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
