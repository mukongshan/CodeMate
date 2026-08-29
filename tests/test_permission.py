"""测试权限控制系统。"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from src.permission.manager import PermissionManager, PermissionLevel
from src.permission.rules import is_safe_path, is_dangerous_command, is_system_path


class TestPermissionRules:
    """测试权限规则函数。"""

    def test_safe_path_inside_workspace(self):
        """测试 workspace 内的路径判断为安全。"""
        workspace = "/home/user/project"
        assert is_safe_path("/home/user/project/src/main.py", workspace)
        assert is_safe_path("src/main.py", workspace)

    def test_unsafe_path_outside_workspace(self):
        """测试 workspace 外的路径判断为不安全。"""
        workspace = "/home/user/project"
        assert not is_safe_path("/etc/passwd", workspace)
        assert not is_safe_path("/home/other/file.txt", workspace)

    def test_system_paths(self):
        """测试系统关键路径识别。"""
        assert is_system_path("/etc/passwd")
        assert is_system_path("/etc/shadow")
        assert is_system_path("C:\\Windows\\System32\\config\\SAM")
        assert not is_system_path("/home/user/file.txt")

    def test_dangerous_commands(self):
        """测试危险命令识别。"""
        dangerous, label = is_dangerous_command("rm -rf /")
        assert dangerous
        assert "删除" in label or "delete" in label.lower()

        dangerous, _ = is_dangerous_command("dd if=/dev/zero of=/dev/sda")
        assert dangerous

        dangerous, _ = is_dangerous_command("ls -la")
        assert not dangerous


class TestPermissionManager:
    """测试权限管理器。"""

    @pytest.fixture
    def manager(self):
        """创建测试权限管理器。"""
        return PermissionManager(workspace="/test/workspace")

    @pytest.mark.asyncio
    async def test_safe_tool_auto_approved(self, manager):
        """测试 SAFE 级工具自动批准。"""
        decision = await manager.check("read_file", {"path": "test.txt"})

        assert decision.allowed
        assert decision.auto_approved
        assert "只读操作" in decision.reason

    @pytest.mark.asyncio
    async def test_write_inside_workspace_auto_approved(self, manager):
        """测试 workspace 内的写操作自动批准。"""
        decision = await manager.check("write_file", {"path": "/test/workspace/file.txt"})

        assert decision.allowed
        assert decision.auto_approved

    @pytest.mark.asyncio
    async def test_system_path_denied(self, manager):
        """测试系统路径写入被拒绝。"""
        decision = await manager.check("write_file", {"path": "/etc/passwd"})

        assert not decision.allowed
        assert "系统关键路径" in decision.reason

    @pytest.mark.asyncio
    async def test_dangerous_command_denied(self, manager):
        """测试危险命令被拒绝。"""
        decision = await manager.check("bash", {"command": "rm -rf /"})

        assert not decision.allowed
        assert "危险命令" in decision.reason

    @pytest.mark.asyncio
    async def test_user_confirmation_required(self, manager):
        """测试需要用户确认的操作。"""
        # 模拟用户确认回调
        manager.ask_user_callback = AsyncMock(return_value={"action": "allow_once"})

        decision = await manager.check("bash", {"command": "echo hello"})

        assert decision.allowed
        assert decision.user_confirmed

    @pytest.mark.asyncio
    async def test_decision_memory(self, manager):
        """测试决策记忆。"""
        manager.ask_user_callback = AsyncMock(return_value={"action": "allow_always"})

        # 第一次需要确认
        decision1 = await manager.check("bash", {"command": "echo test"})
        assert decision1.user_confirmed

        # 第二次自动批准（记忆了决策）
        decision2 = await manager.check("bash", {"command": "echo test"})
        assert decision2.allowed
        assert decision2.auto_approved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
