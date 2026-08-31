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


def test_selective_checkpoint_keeps_unselected_changes_dirty(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "selective-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    workspace = manager.active_workspace("main")
    (workspace / "selected.txt").write_text("selected\n", encoding="utf-8")
    (workspace / "deferred.txt").write_text("deferred\n", encoding="utf-8")

    checkpoint = manager.checkpoint(
        "main", reason="manual", include_paths=["selected.txt"]
    )

    assert checkpoint is not None
    assert manager.status("main")["changed_files"] == ["deferred.txt"]
    assert manager.get_binding("main").sync_state == "dirty"


def test_publish_and_restore_checkpoint(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "publish-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    workspace = manager.active_workspace("main")
    (workspace / "readme.txt").write_text("first\n", encoding="utf-8")
    first = manager.checkpoint("main", reason="manual")
    assert first is not None

    (workspace / "readme.txt").write_text("second\n", encoding="utf-8")
    second = manager.checkpoint("main", reason="manual")
    assert second is not None

    restored = manager.restore_checkpoint("main", first.checkpoint_id)
    assert restored["checkpoint"]["checkpoint_id"] == first.checkpoint_id
    assert (workspace / "readme.txt").read_text(encoding="utf-8") == "first\n"

    published = manager.publish("main", "adopted-result", mode="branch")
    assert published["target_branch"] == "adopted-result"
    assert git(repo, "rev-parse", "adopted-result") == first.commit_sha


def test_publish_squash_creates_formal_commit_without_touching_source(tmp_path):
    repo = create_repo(tmp_path)
    source_before = (repo / "readme.txt").read_text(encoding="utf-8")
    manager = GitLaneManager(
        "squash-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    workspace = manager.active_workspace("main")
    (workspace / "readme.txt").write_text("lane result\n", encoding="utf-8")
    checkpoint = manager.checkpoint("main", reason="manual")
    assert checkpoint is not None

    published = manager.publish("main", "adopted-squash", mode="squash")

    assert published["target_branch"] == "adopted-squash"
    assert git(repo, "show", "adopted-squash:readme.txt") == "lane result"
    assert (repo / "readme.txt").read_text(encoding="utf-8") == source_before


def test_operation_journal_reconciles_unfinished_lane_creation(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "journal-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    manager.create_lane("recoverable", "main")
    operation_id = manager.last_operation_id
    assert operation_id

    manager.store.append_operation(
        {
            "operation_id": operation_id,
            "state": "git_done",
            "timestamp": 0,
        }
    )
    recovered = manager.reconcile_operations({"main"})

    assert recovered == [
        {"operation_id": operation_id, "lane": "recoverable", "action": "rolled_back"}
    ]
    assert not manager.has_binding("recoverable")
    assert manager.store.pending_operations() == []
