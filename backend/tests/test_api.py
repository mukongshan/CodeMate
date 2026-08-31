"""API 集成测试。"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import shutil
import asyncio
from types import SimpleNamespace

from main import create_app
from src.config import AppConfig
from src.api import routes as api_routes
from src.api.ws import _handle_message


@pytest.fixture
def temp_dir():
    """创建临时测试目录。"""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def test_app(temp_dir, monkeypatch):
    """创建测试应用。"""
    # 设置测试环境变量
    monkeypatch.setenv("DATA_DIR", str(temp_dir / "sessions"))
    monkeypatch.setenv("LOG_DIR", str(temp_dir / "logs"))
    monkeypatch.setenv("CODEMATE_WORKTREE_ROOT", str(temp_dir / "worktrees"))
    monkeypatch.setenv("WORKSPACE", str(temp_dir / "workspace"))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    (temp_dir / "workspace").mkdir(exist_ok=True)

    app = create_app()
    return app


@pytest.fixture
def client(test_app):
    """创建测试客户端。"""
    return TestClient(test_app)


class TestHealthEndpoints:
    """测试健康检查端点。"""

    def test_root(self, client):
        """测试根路径。"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "CodeMate"
        assert data["status"] == "running"

    def test_health(self, client):
        """测试健康检查。"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestSessionAPI:
    """测试 Session 管理 API。"""

    def test_create_session(self, client):
        """测试创建会话。"""
        response = client.post("/api/sessions")
        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert "current_lane" in data
        assert data["current_lane"] == "main"

    def test_create_session_with_id(self, client):
        """测试创建指定 ID 的会话。"""
        response = client.post(
            "/api/sessions",
            json={"session_id": "test-123"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] == "test-123"

    def test_create_session_with_workspace(self, client, temp_dir):
        """测试创建会话时绑定工作区目录。"""
        workspace = temp_dir / "custom-workspace"
        workspace.mkdir()

        response = client.post(
            "/api/sessions",
            json={"session_id": "workspace-test", "workspace": str(workspace)},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["workspace"] == str(workspace.resolve())

        detail = client.get("/api/sessions/workspace-test").json()
        assert detail["workspace"] == str(workspace.resolve())

        sessions = client.get("/api/sessions").json()["sessions"]
        listed = next(item for item in sessions if item["session_id"] == "workspace-test")
        assert listed["workspace"] == str(workspace.resolve())

    def test_list_sessions(self, client):
        """测试列出所有会话。"""
        # 先创建一个会话
        client.post("/api/sessions", json={"session_id": "test-session"})

        # 列出会话
        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_get_session(self, client):
        """测试获取单个会话详情。"""
        # 创建会话
        create_resp = client.post("/api/sessions", json={"session_id": "test-get"})
        session_id = create_resp.json()["session_id"]

        # 获取详情
        response = client.get(f"/api/sessions/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert "lanes" in data
        assert "entries" in data
        assert "current_lane" in data

    def test_get_nonexistent_session(self, client):
        """测试获取不存在的会话。"""
        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_agent_is_bound_to_the_active_lane_workspace(self, test_app, temp_dir):
        repo = temp_dir / "agent-repo"
        repo.mkdir()
        import subprocess

        def run_git(*args):
            return subprocess.run(
                ["git", "-C", str(repo), *args],
                check=True,
                capture_output=True,
                text=True,
            )

        run_git("init")
        run_git("config", "user.name", "Test User")
        run_git("config", "user.email", "test@example.com")
        (repo / "main.txt").write_text("main\n", encoding="utf-8")
        run_git("add", "main.txt")
        run_git("commit", "-m", "initial")

        runtime = test_app.state.session_manager.create("agent-lane", str(repo))
        payload = runtime.create_lane("feature", None)
        workspace = Path(payload["git"]["workspace"])
        agent = runtime.build_agent("feature")

        assert agent.workspace == workspace.resolve()
        assert agent.provider.lane == "feature"
        assert agent.tool_registry.get_tool("read_file").workspace == workspace.resolve()
        assert str(workspace.resolve()) in (agent.system_prompt or "")
        assert "用户主仓库目录" in (agent.system_prompt or "")

    def test_delete_session(self, client):
        """测试删除会话。"""
        # 创建会话
        create_resp = client.post("/api/sessions", json={"session_id": "test-delete"})
        session_id = create_resp.json()["session_id"]

        # 删除会话
        response = client.delete(f"/api/sessions/{session_id}")
        assert response.status_code == 204

        # 验证已删除
        get_resp = client.get(f"/api/sessions/{session_id}")
        assert get_resp.status_code == 400


class TestFilesystemAPI:
    """测试本地目录选择和工作区文件 API。"""

    def test_pick_directory(self, client, temp_dir, monkeypatch):
        selected = temp_dir / "selected"
        selected.mkdir()
        monkeypatch.setattr(
            api_routes,
            "_pick_directory_with_windows_dialog",
            lambda initial_path=None: selected,
        )

        response = client.post(
            "/api/filesystem/pick-directory",
            params={"initial_path": str(temp_dir)},
        )
        assert response.status_code == 200
        assert response.json()["path"] == str(selected)

    def test_list_and_read_workspace_files(self, client, temp_dir):
        workspace = temp_dir / "file-viewer-workspace"
        (workspace / "src").mkdir(parents=True)
        (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (workspace / ".git").mkdir()

        create = client.post(
            "/api/sessions",
            json={"session_id": "file-viewer", "workspace": str(workspace)},
        )
        assert create.status_code == 201

        root = client.get("/api/sessions/file-viewer/workspace/files")
        assert root.status_code == 200
        root_data = root.json()
        assert root_data["lane"] == "main"
        assert {entry["name"] for entry in root_data["entries"]} == {"src"}

        directory = client.get(
            "/api/sessions/file-viewer/workspace/files",
            params={"path": "src"},
        )
        assert directory.status_code == 200
        assert directory.json()["entries"][0]["path"] == "src/main.py"

        file_response = client.get(
            "/api/sessions/file-viewer/workspace/file",
            params={"path": "src/main.py"},
        )
        assert file_response.status_code == 200
        assert file_response.json()["content"].replace("\r\n", "\n") == "print('hello')\n"
        assert file_response.json()["binary"] is False

    def test_workspace_file_path_is_confined(self, client, temp_dir):
        workspace = temp_dir / "confined-workspace"
        workspace.mkdir()
        (temp_dir / "outside.txt").write_text("secret", encoding="utf-8")
        client.post(
            "/api/sessions",
            json={"session_id": "confined", "workspace": str(workspace)},
        )

        response = client.get(
            "/api/sessions/confined/workspace/file",
            params={"path": "../outside.txt"},
        )
        assert response.status_code == 400

    def test_workspace_git_metadata_is_hidden(self, client, temp_dir):
        workspace = temp_dir / "git-metadata-workspace"
        (workspace / ".git").mkdir(parents=True)
        (workspace / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        client.post(
            "/api/sessions",
            json={"session_id": "git-metadata", "workspace": str(workspace)},
        )

        response = client.get(
            "/api/sessions/git-metadata/workspace/file",
            params={"path": ".git/config"},
        )
        assert response.status_code == 403

    def test_workspace_binary_file_is_not_decoded(self, client, temp_dir):
        workspace = temp_dir / "binary-workspace"
        workspace.mkdir()
        (workspace / "image.bin").write_bytes(b"\x00\x01\x02")
        client.post(
            "/api/sessions",
            json={"session_id": "binary-viewer", "workspace": str(workspace)},
        )

        response = client.get(
            "/api/sessions/binary-viewer/workspace/file",
            params={"path": "image.bin"},
        )
        assert response.status_code == 200
        assert response.json()["binary"] is True
        assert response.json()["content"] is None


class TestLaneAPI:
    """测试 Lane 分支管理 API。"""

    @pytest.fixture
    def session_id(self, client):
        """创建测试会话。"""
        response = client.post("/api/sessions")
        return response.json()["session_id"]

    def test_list_lanes(self, client, session_id):
        """测试列出分支。"""
        response = client.get(f"/api/sessions/{session_id}/lanes")
        assert response.status_code == 200
        data = response.json()
        assert "current_lane" in data
        assert "lanes" in data
        assert len(data["lanes"]) >= 1  # 至少有 main

    def test_create_lane(self, client, session_id):
        """测试创建新分支。"""
        response = client.post(
            f"/api/sessions/{session_id}/lanes",
            json={
                "name": "feature-test",
                "description": "Test feature branch"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["lane"] == "feature-test"
        assert data["description"] == "Test feature branch"

    def test_create_duplicate_lane(self, client, session_id):
        """测试创建重复分支名。"""
        # 创建第一个
        client.post(
            f"/api/sessions/{session_id}/lanes",
            json={"name": "duplicate"}
        )

        # 尝试创建重复的
        response = client.post(
            f"/api/sessions/{session_id}/lanes",
            json={"name": "duplicate"}
        )
        assert response.status_code == 400

    def test_switch_lane(self, client, session_id):
        """测试切换分支。"""
        # 创建新分支
        client.post(
            f"/api/sessions/{session_id}/lanes",
            json={"name": "switch-test"}
        )

        # 切换分支
        response = client.post(f"/api/sessions/{session_id}/lanes/switch-test/switch")
        assert response.status_code == 200
        data = response.json()
        assert data["lane"] == "switch-test"

    def test_delete_lane(self, client, session_id):
        """测试删除分支。"""
        # 创建分支
        client.post(
            f"/api/sessions/{session_id}/lanes",
            json={"name": "delete-test"}
        )
        client.post(f"/api/sessions/{session_id}/lanes/main/switch")

        # 删除分支
        response = client.delete(f"/api/sessions/{session_id}/lanes/delete-test")
        assert response.status_code == 204

    def test_cannot_delete_main(self, client, session_id):
        """测试不能删除 main 分支。"""
        response = client.delete(f"/api/sessions/{session_id}/lanes/main")
        assert response.status_code == 400

    def test_compare_lanes(self, client, session_id):
        """测试对比两个分支。"""
        # 创建第二个分支
        client.post(
            f"/api/sessions/{session_id}/lanes",
            json={"name": "compare-test"}
        )

        # 对比分支
        response = client.get(
            f"/api/sessions/{session_id}/lanes/compare",
            params={"a": "main", "b": "compare-test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "common_ancestor" in data
        assert "lane_a_diff" in data
        assert "lane_b_diff" in data


class TestGitLaneAPI:
    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        import subprocess

        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def _create_repo(self, temp_dir: Path) -> Path:
        repo = temp_dir / "git-workspace"
        repo.mkdir()
        self._git(repo, "init")
        self._git(repo, "config", "user.name", "Test User")
        self._git(repo, "config", "user.email", "test@example.com")
        (repo / "app.py").write_text("value = 'base'\n", encoding="utf-8")
        self._git(repo, "add", "app.py")
        self._git(repo, "commit", "-m", "initial")
        return repo

    def test_git_lane_checkpoint_worktree_and_file_diff(self, client, temp_dir):
        repo = self._create_repo(temp_dir)
        create = client.post(
            "/api/sessions",
            json={"session_id": "git-lanes", "workspace": str(repo)},
        )
        assert create.status_code == 201
        assert create.json()["git_enabled"] is True

        snapshot = client.get("/api/sessions/git-lanes").json()
        main = next(item for item in snapshot["lanes"] if item["lane"] == "main")
        main_workspace = Path(main["git"]["workspace"])
        assert main_workspace == repo.resolve()
        assert main_workspace.exists()

        (main_workspace / "app.py").write_text("value = 'main'\n", encoding="utf-8")
        create_lane = client.post(
            "/api/sessions/git-lanes/lanes",
            json={"name": "feature-x"},
        )
        assert create_lane.status_code == 201
        feature = create_lane.json()
        assert feature["lane"] == "feature-x"
        assert feature["git"]["enabled"] is True
        assert feature["git"]["workspace"] != str(main_workspace)
        assert feature["git"]["managed_branch"] in self._git(repo, "branch", "--list")

        feature_workspace = Path(feature["git"]["workspace"])
        (feature_workspace / "app.py").write_text("value = 'feature'\n", encoding="utf-8")
        (feature_workspace / "feature.py").write_text("enabled = True\n", encoding="utf-8")
        checkpoint = client.post(
            "/api/sessions/git-lanes/lanes/feature-x/checkpoint"
        )
        assert checkpoint.status_code == 200
        assert checkpoint.json()["created"] is True

        comparison = client.get(
            "/api/sessions/git-lanes/lanes/compare",
            params={"a": "main", "b": "feature-x"},
        )
        assert comparison.status_code == 200
        code = comparison.json()["code"]
        assert code["enabled"] is True
        assert {item["path"] for item in code["files"]} == {"app.py", "feature.py"}

        file_diff = client.get(
            "/api/sessions/git-lanes/lanes/compare/file",
            params={"a": "main", "b": "feature-x", "path": "app.py"},
        )
        assert file_diff.status_code == 200
        assert "value = 'main'" in file_diff.json()["diff"]
        assert "value = 'feature'" in file_diff.json()["diff"]
        assert (repo / "app.py").read_text(encoding="utf-8") == "value = 'main'\n"

    def test_sensitive_file_blocks_structural_checkpoint(self, client, temp_dir):
        repo = self._create_repo(temp_dir)
        response = client.post(
            "/api/sessions",
            json={"session_id": "blocked-checkpoint", "workspace": str(repo)},
        )
        workspace = Path(
            client.get("/api/sessions/blocked-checkpoint").json()["workspace"]
        )
        (workspace / ".env").write_text("API_KEY=secret\n", encoding="utf-8")

        create_lane = client.post(
            "/api/sessions/blocked-checkpoint/lanes",
            json={"name": "unsafe-lane"},
        )
        assert create_lane.status_code == 400
        assert create_lane.json()["error"]["code"] == "CHECKPOINT_BLOCKED"
        lanes = client.get("/api/sessions/blocked-checkpoint/lanes").json()["lanes"]
        assert {item["lane"] for item in lanes} == {"main"}

    def test_checkpoint_history_publish_and_archive(self, client, temp_dir):
        repo = self._create_repo(temp_dir)
        client.post(
            "/api/sessions",
            json={"session_id": "lifecycle-api", "workspace": str(repo)},
        )
        snapshot = client.get("/api/sessions/lifecycle-api").json()
        main_workspace = Path(snapshot["workspace"])
        (main_workspace / "app.py").write_text("value = 'published'\n", encoding="utf-8")

        checkpoint = client.post(
            "/api/sessions/lifecycle-api/lanes/main/checkpoint",
            json={"paths": ["app.py"]},
        )
        assert checkpoint.status_code == 200
        checkpoint_id = checkpoint.json()["checkpoint"]["checkpoint_id"]

        history = client.get(
            "/api/sessions/lifecycle-api/lanes/main/checkpoints"
        )
        assert history.status_code == 200
        assert any(item["checkpoint_id"] == checkpoint_id for item in history.json()["checkpoints"])

        publish = client.post(
            "/api/sessions/lifecycle-api/lanes/main/publish",
            json={"target_branch": "feature/published", "mode": "branch"},
        )
        assert publish.status_code == 200
        assert publish.json()["target_branch"] == "feature/published"

        (main_workspace / "app.py").write_text("value = 'published again'\n", encoding="utf-8")
        second_checkpoint = client.post(
            "/api/sessions/lifecycle-api/lanes/main/checkpoint",
            json={"paths": ["app.py"]},
        )
        assert second_checkpoint.status_code == 200
        republish = client.post(
            "/api/sessions/lifecycle-api/lanes/main/publish",
            json={"target_branch": "feature/published", "mode": "branch"},
        )
        assert republish.status_code == 200
        assert republish.json()["action"] == "updated"
        assert republish.json()["publication_count"] == 2

        create_lane = client.post(
            "/api/sessions/lifecycle-api/lanes",
            json={"name": "archive-me"},
        )
        assert create_lane.status_code == 201
        client.post("/api/sessions/lifecycle-api/lanes/main/switch")
        archive = client.post(
            "/api/sessions/lifecycle-api/lanes/archive-me/archive"
        )
        assert archive.status_code == 200
        assert archive.json()["archived"] is True
        active = client.get("/api/sessions/lifecycle-api/lanes").json()["lanes"]
        assert {item["lane"] for item in active} == {"main"}

        restore_lane = client.post(
            "/api/sessions/lifecycle-api/lanes/archive-me/restore-lane"
        )
        assert restore_lane.status_code == 200
        assert restore_lane.json()["archived"] is False


class TestPermissionAPI:
    """测试权限审计 API。"""

    @pytest.fixture
    def session_id(self, client):
        """创建测试会话。"""
        response = client.post("/api/sessions")
        return response.json()["session_id"]

    def test_permission_audit(self, client, session_id):
        """测试权限审计报告。"""
        response = client.get(f"/api/sessions/{session_id}/permissions/audit")
        assert response.status_code == 200
        data = response.json()
        assert "total_decisions" in data
        assert "allowed" in data
        assert "denied" in data
        assert "tool_breakdown" in data

    def test_permission_gate_can_be_read_and_updated(self, client, session_id):
        response = client.get(f"/api/sessions/{session_id}/permissions/gate")
        assert response.status_code == 200
        assert "git push" in response.json()["command_blacklist"]

        response = client.put(
            f"/api/sessions/{session_id}/permissions/gate",
            json={"command_blacklist": [" Echo ", "git status", "echo"]},
        )
        assert response.status_code == 200
        assert response.json()["command_blacklist"] == ["echo", "git status"]

        detail = client.get(f"/api/sessions/{session_id}").json()
        assert detail["command_blacklist"] == ["echo", "git status"]


class TestWebSocketEndpoint:
    """测试 WebSocket 端点是否真的挂载在 app 上。

    这一层过去没有测试，导致 ws router 漏挂载一直没被发现——
    test_websocket_events.py 是直接构造 Agent 验事件字段的，绕开了 HTTP 层。
    """

    def test_ws_route_is_mounted(self, test_app):
        """/ws/{session_id} 必须出现在 app 的路由表里。

        用递归收集：不同 FastAPI 版本对 include_router 的表示不同，有的把子
        路由摊平进 app.routes，有的留一层 _IncludedRouter 包装——后者把真实
        子路由挂在 original_router 上，不暴露 routes 属性。WebSocket 路由不
        进 OpenAPI，所以只能从路由表本身查。
        """

        def collect(routes):
            for route in routes:
                path = getattr(route, "path", None)
                if path:
                    yield path
                yield from collect(getattr(route, "routes", []))
                nested = getattr(route, "original_router", None)
                if nested is not None:
                    yield from collect(getattr(nested, "routes", []))

        assert "/ws/{session_id}" in set(collect(test_app.routes))

    def test_ws_connect_existing_session(self, client):
        """已存在的 session 能建连，且不会立刻收到 error 事件。"""
        create_resp = client.post("/api/sessions", json={"session_id": "ws-ok"})
        assert create_resp.status_code == 201

        with client.websocket_connect("/ws/ws-ok") as ws:
            # 发一个未知类型的消息：服务端只记日志、不回包也不断开连接。
            ws.send_json({"type": "__unknown__"})
            # 再发一个格式错误的 send_message，应当收到 INVALID_REQUEST。
            ws.send_json({"type": "send_message"})
            payload = ws.receive_json()
            assert payload["type"] == "error"
            assert payload["data"]["code"] == "INVALID_REQUEST"

    def test_ws_connect_unknown_session(self, client):
        """不存在的 session 建连后收到 SESSION_NOT_FOUND 并被关闭。"""
        with client.websocket_connect("/ws/does-not-exist") as ws:
            payload = ws.receive_json()
            assert payload["type"] == "error"
            assert payload["data"]["code"] == "SESSION_NOT_FOUND"

    def test_ws_permission_response_unmatched(self, client):
        """未命中的 permission_response 只记日志，不打断连接。"""
        client.post("/api/sessions", json={"session_id": "ws-perm"})

        with client.websocket_connect("/ws/ws-perm") as ws:
            ws.send_json(
                {
                    "type": "permission_response",
                    "request_id": "perm_nonexistent",
                    "action": "deny",
                }
            )
            # 连接仍然可用：后续的坏消息照样能拿到回包。
            ws.send_json({"type": "send_message"})
            payload = ws.receive_json()
            assert payload["type"] == "error"

    @pytest.mark.asyncio
    async def test_send_message_task_allows_permission_response(self):
        class FakeRuntime:
            def __init__(self):
                self.perm_event = asyncio.Event()

            async def run(self, content, lane=None):
                await self.perm_event.wait()
                return SimpleNamespace(
                    run_id="run-1",
                    status="completed",
                    iterations=1,
                    total_tokens=1,
                    duration=0.1,
                )

            async def emit(self, *args, **kwargs):
                return None

            def resolve_permission(self, request_id, action):
                if request_id == "perm-1" and action == "allow_once":
                    self.perm_event.set()
                    return True
                return False

        runtime = FakeRuntime()

        task = await asyncio.wait_for(
            _handle_message(runtime, {"type": "send_message", "content": "hello"}),
            timeout=0.5,
        )
        assert task is not None

        await asyncio.sleep(0)
        assert not task.done()

        await asyncio.wait_for(
            _handle_message(
                runtime,
                {
                    "type": "permission_response",
                    "request_id": "perm-1",
                    "action": "allow_once",
                },
            ),
            timeout=0.5,
        )

        await asyncio.wait_for(task, timeout=0.5)


class TestRiskLevelNormalization:
    """risk_level 归一化：permission 层传 low/medium/high，不能被降级。"""

    def test_passthrough_and_mapping(self):
        from src.permission.manager import normalize_risk_level

        # _ask_user 实际传出的取值必须原样透传——high 不能变 medium。
        assert normalize_risk_level("high") == "high"
        assert normalize_risk_level("medium") == "medium"
        assert normalize_risk_level("low") == "low"
        # 兼容按 PermissionLevel 名字传入的调用点。
        assert normalize_risk_level("dangerous") == "high"
        assert normalize_risk_level("write") == "medium"
        assert normalize_risk_level("safe") == "low"
        # 未知取值保守落到 medium。
        assert normalize_risk_level("") == "medium"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
