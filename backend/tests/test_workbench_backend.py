from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api.workspace_files import read_file, restore_file, search_workspace, write_file
from src.tools.file_tools import EditFileTool
from src.version_control.manager import GitLaneManager


def _git(repo: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "note.txt").write_text("before\n", encoding="utf-8")
    _git(repo, "add", "note.txt")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_editor_save_returns_revision_and_rejects_stale_content(tmp_path: Path):
    file_path = tmp_path / "note.txt"
    file_path.write_text("before\n", encoding="utf-8")

    loaded = read_file(tmp_path, "note.txt")
    saved = write_file(tmp_path, "note.txt", "after\n", encoding=loaded["encoding"], expected_revision=loaded["revision"])

    assert saved["content"] == "after\n"
    assert saved["revision"] != loaded["revision"]

    file_path.write_text("external\n", encoding="utf-8")
    with pytest.raises(HTTPException) as raised:
        write_file(tmp_path, "note.txt", "overwrite\n", expected_revision=saved["revision"])
    assert raised.value.status_code == 409


def test_editor_save_rejects_git_metadata_and_binary_files(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "binary.dat").write_bytes(b"\x00\x01")

    with pytest.raises(HTTPException) as metadata_error:
        write_file(tmp_path, ".git/config", "unsafe")
    assert metadata_error.value.status_code == 403

    with pytest.raises(HTTPException) as binary_error:
        write_file(tmp_path, "binary.dat", "text")
    assert binary_error.value.status_code == 400


def test_workspace_search_matches_names_and_content_without_git_metadata(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("const Ready = true;\nneedle here\n", encoding="utf-8")
    (tmp_path / "needle.txt").write_text("other\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("needle\n", encoding="utf-8")

    result = search_workspace(tmp_path, "needle")

    assert result["files_matched"] == 2
    assert {item["path"] for item in result["results"]} == {"src/app.ts", "needle.txt"}
    assert any(item["path"] == "src/app.ts" and item["line"] == 2 for item in result["results"])

    with pytest.raises(HTTPException) as metadata_error:
        search_workspace(tmp_path, "needle", ".git")
    assert metadata_error.value.status_code == 403


@pytest.mark.asyncio
async def test_file_change_metadata_supports_exact_rollback(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_bytes("before\n".encode("utf-8"))
    tool = EditFileTool(tmp_path)

    result = await tool.execute(path="note.txt", old_string="before", new_string="after")
    rollback = result.metadata["file_change"]["rollback"]
    import base64

    restored = restore_file(
        tmp_path,
        "note.txt",
        base64.b64decode(rollback["before_base64"]),
        rollback["before_exists"],
        rollback["after_revision"],
    )

    assert restored["content"] == "before\n"
    assert target.read_text(encoding="utf-8") == "before\n"


def test_ordinary_git_stage_unstage_commit_is_lane_scoped(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = GitLaneManager("workbench-session", repo, tmp_path / "data", tmp_path / "worktrees", 1024 * 1024)
    (repo / "note.txt").write_text("changed\n", encoding="utf-8")

    status = manager.git_status("main")
    assert status["files"][0]["path"] == "note.txt"
    assert status["files"][0]["unstaged"] is True

    manager.git_stage("main", ["note.txt"])
    staged = manager.git_status("main")
    assert staged["files"][0]["staged"] is True

    manager.git_unstage("main", ["note.txt"])
    unstaged = manager.git_status("main")
    assert unstaged["files"][0]["unstaged"] is True

    manager.git_stage("main", ["note.txt"])
    committed = manager.git_commit("main", "update note")
    assert committed["files"] == []
    assert _git(repo, "log", "-1", "--pretty=%s") == "update note"
