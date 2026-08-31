from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.errors.types import AgentError
from src.version_control.manager import GitLaneManager


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def create_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "readme.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "readme.txt")
    git(repo, "commit", "-m", "initial")
    return repo


def test_non_git_workspace_disables_integration(tmp_path):
    workspace = tmp_path / "plain"
    workspace.mkdir()
    manager = GitLaneManager(
        "plain-session",
        workspace,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )

    assert manager.enabled is False
    assert manager.active_workspace("main") == workspace
    assert manager.compare("main", "main")["enabled"] is False


def test_checkpoint_creates_shared_repository_commit(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "checkpoint-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )

    workspace = manager.active_workspace("main")
    (workspace / "readme.txt").write_text("changed\n", encoding="utf-8")
    checkpoint = manager.checkpoint("main", reason="manual")

    assert checkpoint is not None
    assert git(repo, "cat-file", "-t", checkpoint.commit_sha) == "commit"
    assert manager.status("main")["changed_files"] == []
    assert (repo / "readme.txt").read_text(encoding="utf-8") == "base\n"


def test_sensitive_file_is_not_committed(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "secret-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    workspace = manager.active_workspace("main")
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")

    with pytest.raises(AgentError) as raised:
        manager.checkpoint("main", reason="manual")

    assert raised.value.code == "CHECKPOINT_BLOCKED"
    assert (workspace / ".env").exists()
    assert manager.status("main")["changed_files"] == [".env"]


def test_external_managed_branch_commit_is_marked_out_of_sync(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "external-change-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    workspace = manager.active_workspace("main")
    (workspace / "readme.txt").write_text("external\n", encoding="utf-8")
    git(workspace, "add", "readme.txt")
    git(workspace, "commit", "-m", "external managed branch commit")

    lane_state = manager.lane_api("main")
    assert lane_state["sync_state"] == "out_of_sync"

    with pytest.raises(AgentError) as raised:
        manager.checkpoint("main", reason="manual")

    assert raised.value.code == "GIT_OPERATION_FAILED"
