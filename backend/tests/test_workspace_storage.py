from __future__ import annotations

import json

from src.storage.workspace_storage import WorkspaceStorage


def test_migrate_legacy_flat_session_into_workspace_hierarchy(tmp_path):
    legacy_root = tmp_path / "sessions"
    workspace_dir = tmp_path / "project"
    legacy_root.mkdir()
    workspace_dir.mkdir()
    (legacy_root / "legacy.jsonl").write_text("{\"id\": \"entry-1\"}\n", encoding="utf-8")
    (legacy_root / "legacy_lanes.jsonl").write_text(
        "{\"lane\": \"main\", \"leaf_id\": null, \"seq\": 1}\n",
        encoding="utf-8",
    )
    (legacy_root / "legacy_meta.json").write_text(
        json.dumps({"workspace": str(workspace_dir), "title": "旧会话"}),
        encoding="utf-8",
    )

    storage = WorkspaceStorage(legacy_root)
    plan = storage.legacy_migration_plan(workspace_dir)
    assert plan == [
        {
            "session_id": "legacy",
            "workspace": str(workspace_dir),
            "title": "旧会话",
            "files": [
                str(legacy_root / "legacy.jsonl"),
                str(legacy_root / "legacy_lanes.jsonl"),
            ],
        }
    ]
    migrated = storage.migrate_legacy_sessions(workspace_dir)

    assert migrated == 1
    workspace = storage.list_workspaces()[0]
    paths = storage.session_paths(workspace.workspace_id, "legacy")
    assert paths.entries.exists()
    assert paths.lanes.exists()
    assert storage.read_session_meta(paths)["title"] == "旧会话"
    assert workspace.session_ids == ["legacy"]
    assert not (legacy_root / "legacy.jsonl").exists()
    assert not (legacy_root / "legacy_lanes.jsonl").exists()
    assert not (legacy_root / "legacy_meta.json").exists()


def test_empty_registry_is_backed_up_and_reinitialized(tmp_path):
    legacy_root = tmp_path / "sessions"
    registry = tmp_path / "workspaces" / "registry.json"
    registry.parent.mkdir()
    registry.write_text("", encoding="utf-8")

    storage = WorkspaceStorage(legacy_root)

    assert storage.list_workspaces() == []
    assert json.loads(registry.read_text(encoding="utf-8")) == {
        "version": 1,
        "workspace_order": [],
        "workspaces": {},
        "pending_mutation": None,
    }
    backups = list(registry.parent.glob("registry.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == ""


def test_corrupt_registry_is_rebuilt_from_session_metadata(tmp_path):
    legacy_root = tmp_path / "sessions"
    workspace_dir = tmp_path / "project"
    workspace_dir.mkdir()
    registry = tmp_path / "workspaces" / "registry.json"
    registry.parent.mkdir()
    registry.write_text("{broken", encoding="utf-8")
    session_meta = (
        registry.parent
        / "workspace-1"
        / "sessions"
        / "session-1"
        / "session.json"
    )
    session_meta.parent.mkdir(parents=True)
    session_meta.write_text(
        json.dumps(
            {
                "workspace_id": "workspace-1",
                "session_id": "session-1",
                "workspace": str(workspace_dir),
                "workspace_title": "演示工作区",
                "title": "会话一",
                "created_at": 10,
                "updated_at": 20,
            }
        ),
        encoding="utf-8",
    )

    storage = WorkspaceStorage(legacy_root)

    workspace = storage.list_workspaces()[0]
    assert workspace.workspace_id == "workspace-1"
    assert workspace.path == str(workspace_dir)
    assert workspace.title == "演示工作区"
    assert workspace.session_ids == ["session-1"]
    assert storage.find_session("session-1") is not None
    assert json.loads(registry.read_text(encoding="utf-8"))["workspace_order"] == [
        "workspace-1"
    ]
