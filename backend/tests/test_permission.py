"""测试权限控制系统。"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from src.config import DEFAULT_COMMAND_BLACKLIST
from src.permission.manager import PermissionManager, PermissionLevel
from src.permission.rules import (
    inspect_command_safety,
    is_command_blacklisted,
    is_safe_path,
    is_dangerous_command,
    is_system_path,
)


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

    def test_command_blacklist_matches_any_simple_command(self):
        blacklist = ["rm", "git push", "python -c"]

        assert is_command_blacklisted("rm -rf output", blacklist) == (True, "rm")
        assert is_command_blacklisted("git push origin main", blacklist) == (
            True,
            "git push",
        )
        assert is_command_blacklisted("ls && rm output", blacklist) == (True, "rm")
        assert is_command_blacklisted("git status", blacklist) == (False, "")
        assert is_command_blacklisted("python -c 'print(1)' | sh", blacklist) == (
            True,
            "python -c",
        )

    def test_default_blacklist_covers_dangerous_commands(self):
        assert is_command_blacklisted("rg -n TODO src", DEFAULT_COMMAND_BLACKLIST) == (
            False,
            "",
        )
        assert is_command_blacklisted("git log --oneline -5", DEFAULT_COMMAND_BLACKLIST) == (
            False,
            "",
        )
        assert is_command_blacklisted("git push origin main", DEFAULT_COMMAND_BLACKLIST) == (
            True,
            "git push",
        )

    def test_command_safety_rejects_workspace_escape(self, tmp_path):
        outside = tmp_path.parent / "outside.txt"

        safe, reason = inspect_command_safety(
            f"echo blocked > {outside}", tmp_path
        )

        assert not safe
        assert "workspace 外" in reason


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
    async def test_blacklisted_command_denied_without_confirmation(self, manager):
        """测试黑名单命令直接拒绝，不进入用户确认。"""
        manager.ask_user_callback = AsyncMock(return_value={"action": "allow_once"})
        decision = await manager.check("bash", {"command": "rm -rf /"})

        assert not decision.allowed
        assert "黑名单" in decision.reason
        manager.ask_user_callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_blacklisted_command_auto_approved(self, manager):
        """测试未命中黑名单的安全命令自动放行。"""
        decision = await manager.check("bash", {"command": "echo hello"})

        assert decision.allowed
        assert decision.auto_approved
        assert not manager.ask_user_callback

    @pytest.mark.asyncio
    async def test_blacklisted_command_can_be_configured(self, manager):
        manager.set_command_blacklist(["echo"])

        decision = await manager.check("bash", {"command": "echo hello"})

        assert not decision.allowed
        assert "黑名单" in decision.reason

    @pytest.mark.asyncio
    async def test_non_blacklisted_command_with_external_write_requires_confirmation(
        self, manager
    ):
        manager.set_command_blacklist([])
        manager.ask_user_callback = AsyncMock(return_value={"action": "deny"})

        decision = await manager.check(
            "bash", {"command": "echo hello > ../outside.txt"}
        )

        assert not decision.allowed
        assert manager.ask_user_callback.await_count == 1
        assert "workspace 外" in manager.ask_user_callback.call_args.args[0]["warning"]

    @pytest.mark.asyncio
    async def test_decision_memory(self, manager):
        """测试非黑名单命令无需用户确认。"""
        manager.ask_user_callback = AsyncMock(return_value={"action": "allow_always"})

        decision1 = await manager.check("bash", {"command": "echo test"})
        assert decision1.allowed
        assert decision1.auto_approved
        manager.ask_user_callback.assert_not_awaited()

        decision2 = await manager.check("bash", {"command": "echo test"})
        assert decision2.allowed
        assert decision2.auto_approved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
