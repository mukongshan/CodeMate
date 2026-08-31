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
    assert workspace == repo
    assert manager.get_binding("main").worktree_path == str(repo.resolve())
    (workspace / "readme.txt").write_text("changed\n", encoding="utf-8")
    checkpoint = manager.checkpoint("main", reason="manual")

    assert checkpoint is not None
    assert git(repo, "cat-file", "-t", checkpoint.commit_sha) == "commit"
    assert manager.status("main")["changed_files"] == []
    assert (repo / "readme.txt").read_text(encoding="utf-8") == "changed\n"


def test_close_worktrees_preserves_source_main_and_removes_feature(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "close-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    feature = manager.create_lane("feature", "main")
    feature_path = Path(feature.worktree_path)

    manager.close_worktrees()

    assert repo.exists()
    assert manager.active_workspace("main") == repo
    assert not feature_path.exists()


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


def test_external_managed_branch_commit_is_adopted_and_can_continue(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "external-change-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    feature = manager.create_lane("feature", "main")
    workspace = Path(feature.worktree_path)
    (workspace / "readme.txt").write_text("external\n", encoding="utf-8")
    git(workspace, "add", "readme.txt")
    git(workspace, "commit", "-m", "external managed branch commit")

    lane_state = manager.lane_api("feature")
    external_head = git(workspace, "rev-parse", "HEAD")
    assert lane_state["sync_state"] == "clean"
    assert manager.get_binding("feature").head_commit == external_head

    (workspace / "readme.txt").write_text("external plus codemate\n", encoding="utf-8")
    checkpoint = manager.checkpoint("feature", reason="manual")

    assert checkpoint is not None
    assert checkpoint.previous_commit == external_head
    assert git(workspace, "rev-parse", "HEAD") == checkpoint.commit_sha


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


def test_balanced_checkpoint_defers_and_merges_successive_runs(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "balanced-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
        checkpoint_merge_window_seconds=300,
        checkpoint_max_pending_runs=10,
        checkpoint_max_pending_files=20,
        checkpoint_max_pending_seconds=1800,
    )
    workspace = manager.active_workspace("main")

    (workspace / "readme.txt").write_text("run one\n", encoding="utf-8")
    first = manager.defer_run_checkpoint(
        "main", run_id="run-1", conversation_entry_id="entry-1", now=100
    )
    assert first["pending"] is True
    assert first["should_flush"] is False

    (workspace / "readme.txt").write_text("run two\n", encoding="utf-8")
    second = manager.defer_run_checkpoint(
        "main", run_id="run-2", conversation_entry_id="entry-2", now=200
    )
    assert second["pending_run_count"] == 2
    assert second["should_flush"] is False
    assert manager.status("main")["changed_files"] == ["readme.txt"]

    due = manager.pending_checkpoint_status("main", now=501)
    assert due["should_flush"] is True
    checkpoint = manager.checkpoint("main", reason="run_completed_batch")
    assert checkpoint is not None
    assert checkpoint.run_ids == ["run-1", "run-2"]
    assert checkpoint.conversation_entry_ids == ["entry-1", "entry-2"]
    assert manager.get_binding("main").pending_run_ids == []


def test_balanced_checkpoint_flushes_when_run_limit_is_reached(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "balanced-limit-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
        checkpoint_merge_window_seconds=300,
        checkpoint_max_pending_runs=2,
    )
    workspace = manager.active_workspace("main")

    (workspace / "one.txt").write_text("one\n", encoding="utf-8")
    manager.defer_run_checkpoint("main", run_id="run-1", now=100)
    (workspace / "two.txt").write_text("two\n", encoding="utf-8")
    due = manager.defer_run_checkpoint("main", run_id="run-2", now=101)

    assert due["should_flush"] is True
    assert "max_pending_runs" in due["flush_reasons"]


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


def test_branch_publish_can_fast_forward_the_same_target(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "republish-branch-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    feature = manager.create_lane("feature", "main")
    workspace = Path(feature.worktree_path)
    (workspace / "readme.txt").write_text("first publish\n", encoding="utf-8")
    first = manager.checkpoint("feature", reason="manual")
    assert first is not None

    created = manager.publish("feature", "feature/result", mode="branch")
    assert created["action"] == "created"
    assert git(repo, "rev-parse", "feature/result") == first.commit_sha

    (workspace / "readme.txt").write_text("second publish\n", encoding="utf-8")
    second = manager.checkpoint("feature", reason="manual")
    assert second is not None
    updated = manager.publish("feature", "feature/result", mode="branch")

    assert updated["action"] == "updated"
    assert updated["previous_published_commit"] == first.commit_sha
    assert updated["publication_count"] == 2
    assert git(repo, "rev-parse", "feature/result") == second.commit_sha
    assert manager.get_binding("feature").published_lane_head == second.commit_sha


def test_republish_rejects_an_externally_moved_target_branch(tmp_path):
    repo = create_repo(tmp_path)
    initial = git(repo, "rev-parse", "HEAD")
    manager = GitLaneManager(
        "republish-external-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    feature = manager.create_lane("feature", "main")
    workspace = Path(feature.worktree_path)
    (workspace / "readme.txt").write_text("published\n", encoding="utf-8")
    assert manager.checkpoint("feature", reason="manual") is not None
    manager.publish("feature", "feature/result", mode="branch")

    git(repo, "branch", "-f", "feature/result", initial)
    (workspace / "readme.txt").write_text("new result\n", encoding="utf-8")
    assert manager.checkpoint("feature", reason="manual") is not None

    with pytest.raises(AgentError) as raised:
        manager.publish("feature", "feature/result", mode="branch")

    assert "CodeMate 之外发生了变化" in raised.value.message
    assert git(repo, "rev-parse", "feature/result") == initial


def test_republish_rejects_a_target_checked_out_in_another_worktree(tmp_path):
    repo = create_repo(tmp_path)
    manager = GitLaneManager(
        "republish-checked-out-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    feature = manager.create_lane("feature", "main")
    workspace = Path(feature.worktree_path)
    (workspace / "readme.txt").write_text("published\n", encoding="utf-8")
    assert manager.checkpoint("feature", reason="manual") is not None
    manager.publish("feature", "feature/result", mode="branch")

    checked_out = tmp_path / "checked-out-result"
    git(repo, "worktree", "add", str(checked_out), "feature/result")
    try:
        (workspace / "readme.txt").write_text("new result\n", encoding="utf-8")
        assert manager.checkpoint("feature", reason="manual") is not None

        with pytest.raises(AgentError) as raised:
            manager.publish("feature", "feature/result", mode="branch")

        assert "正在工作区中检出" in raised.value.message
        assert Path(raised.value.details["worktree"]).resolve() == checked_out.resolve()
    finally:
        git(repo, "worktree", "remove", "--force", str(checked_out))


def test_publish_squash_creates_formal_commit_from_source_main(tmp_path):
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
    assert (repo / "readme.txt").read_text(encoding="utf-8") != source_before


def test_squash_publish_appends_an_incremental_formal_commit(tmp_path):
    repo = create_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    manager = GitLaneManager(
        "republish-squash-session",
        repo,
        tmp_path / "data",
        tmp_path / "worktrees",
        1024 * 1024,
    )
    feature = manager.create_lane("feature", "main")
    workspace = Path(feature.worktree_path)
    (workspace / "readme.txt").write_text("first squash\n", encoding="utf-8")
    first_lane_checkpoint = manager.checkpoint("feature", reason="manual")
    assert first_lane_checkpoint is not None
    first_publish = manager.publish("feature", "feature/squash", mode="squash")
    first_published_commit = first_publish["published_commit"]

    (workspace / "readme.txt").write_text("second squash\n", encoding="utf-8")
    second_lane_checkpoint = manager.checkpoint("feature", reason="manual")
    assert second_lane_checkpoint is not None
    second_publish = manager.publish("feature", "feature/squash", mode="squash")

    assert second_publish["action"] == "updated"
    assert second_publish["previous_published_commit"] == first_published_commit
    assert second_publish["published_commit"] != first_published_commit
    assert git(repo, "show", "feature/squash:readme.txt") == "second squash"
    assert git(repo, "rev-list", "--count", f"{base}..feature/squash") == "2"
    binding = manager.get_binding("feature")
    assert binding.published_lane_head == second_lane_checkpoint.commit_sha
    assert binding.publication_count == 2


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
