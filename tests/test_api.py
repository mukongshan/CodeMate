"""API 集成测试。"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import shutil

from main import create_app
from src.config import AppConfig


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
    monkeypatch.setenv("WORKSPACE", str(temp_dir / "workspace"))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
