"""工作区注册表、Session 分级路径与旧扁平数据迁移。"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


REGISTRY_VERSION = 1


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _canonical_directory(path: Path | str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"工作区路径不是目录: {resolved}")
    return resolved


def _path_key(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=False)))


@dataclass
class WorkspaceRecord:
    workspace_id: str
    path: str
    title: str
    session_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @staticmethod
    def from_dict(data: dict) -> "WorkspaceRecord":
        return WorkspaceRecord(
            workspace_id=str(data["workspace_id"]),
            path=str(data["path"]),
            title=str(data.get("title") or Path(str(data["path"])).name),
            session_ids=[str(item) for item in data.get("session_ids", [])],
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SessionPaths:
    workspace_id: str
    session_id: str
    session_dir: Path
    meta: Path
    entries: Path
    lanes: Path
    git_dir: Path
    logs_dir: Path

    @property
    def git_bindings(self) -> Path:
        return self.git_dir / "bindings.json"

    @property
    def checkpoints(self) -> Path:
        return self.git_dir / "checkpoints.ndjson"

    @property
    def operations(self) -> Path:
        return self.git_dir / "operations.ndjson"

    def ensure(self) -> None:
        (self.session_dir / "conversation").mkdir(parents=True, exist_ok=True)
        self.git_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


class WorkspaceStorage:
    """持久化工作区注册表，并集中生成所有 Session 路径。"""

    def __init__(self, legacy_sessions_dir: Path | str) -> None:
        self.legacy_sessions_dir = Path(legacy_sessions_dir)
        self.data_root = self.legacy_sessions_dir.parent
        self.workspaces_root = self.data_root / "workspaces"
        self.registry_path = self.workspaces_root / "registry.json"
        self.deletions_root = self.data_root / "deletions"
        self._workspaces: dict[str, WorkspaceRecord] = {}
        self._workspace_order: list[str] = []
        self._pending_mutation: Optional[dict] = None
        self._load()

    def _load(self) -> None:
        if not self.registry_path.exists():
            return
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != REGISTRY_VERSION:
            raise ValueError("不支持的工作区注册表版本")
        records = payload.get("workspaces", {})
        self._workspaces = {
            str(workspace_id): WorkspaceRecord.from_dict(record)
            for workspace_id, record in records.items()
        }
        self._workspace_order = [
            str(workspace_id)
            for workspace_id in payload.get("workspace_order", [])
            if str(workspace_id) in self._workspaces
        ]
        for workspace_id in self._workspaces:
            if workspace_id not in self._workspace_order:
                self._workspace_order.append(workspace_id)
        pending = payload.get("pending_mutation")
        self._pending_mutation = pending if isinstance(pending, dict) else None
        if self._pending_mutation is not None:
            self._reconcile_sessions()

    def _payload(self) -> dict:
        return {
            "version": REGISTRY_VERSION,
            "workspace_order": self._workspace_order,
            "workspaces": {
                workspace_id: record.to_dict()
                for workspace_id, record in self._workspaces.items()
            },
            "pending_mutation": self._pending_mutation,
        }

    def _save(self) -> None:
        _atomic_write_json(self.registry_path, self._payload())

    def _begin_mutation(self, operation: str, **details: object) -> None:
        self._pending_mutation = {
            "operation": operation,
            "timestamp": time.time(),
            **details,
        }
        self._save()

    def _finish_mutation(self) -> None:
        self._pending_mutation = None
        self._save()

    def list_workspaces(self) -> list[WorkspaceRecord]:
        return [self._workspaces[item] for item in self._workspace_order]

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceRecord]:
        return self._workspaces.get(workspace_id)

    def resolve_workspace(self, path: Path | str) -> Optional[WorkspaceRecord]:
        key = _path_key(path)
        return next(
            (
                record
                for record in self._workspaces.values()
                if _path_key(record.path) == key
            ),
            None,
        )

    def create_workspace(
        self, path: Path | str, title: Optional[str] = None
    ) -> tuple[WorkspaceRecord, bool]:
        canonical = _canonical_directory(path)
        existing = self.resolve_workspace(canonical)
        if existing is not None:
            return existing, False
        now = time.time()
        workspace_id = uuid.uuid4().hex
        record = WorkspaceRecord(
            workspace_id=workspace_id,
            path=str(canonical),
            title=(title or canonical.name or str(canonical)).strip(),
            created_at=now,
            updated_at=now,
        )
        self._begin_mutation("create_workspace", workspace_id=workspace_id)
        self._workspaces[workspace_id] = record
        self._workspace_order.insert(0, workspace_id)
        self._finish_mutation()
        return record, True

    def rename_workspace(self, workspace_id: str, title: str) -> WorkspaceRecord:
        record = self.require_workspace(workspace_id)
        normalized = title.strip()
        if not normalized:
            raise ValueError("工作区名称不能为空")
        record.title = normalized
        record.updated_at = time.time()
        self._save()
        return record

    def remove_workspace(self, workspace_id: str) -> WorkspaceRecord:
        record = self.require_workspace(workspace_id)
        if record.session_ids:
            raise ValueError("工作区仍包含会话，请先删除会话或使用级联删除")
        self._begin_mutation("remove_workspace", workspace_id=workspace_id)
        self._workspaces.pop(workspace_id, None)
        self._workspace_order = [
            item for item in self._workspace_order if item != workspace_id
        ]
        self._finish_mutation()
        return record

    def require_workspace(self, workspace_id: str) -> WorkspaceRecord:
        record = self.get_workspace(workspace_id)
        if record is None:
            raise KeyError(workspace_id)
        return record

    def session_paths(self, workspace_id: str, session_id: str) -> SessionPaths:
        session_dir = self.workspaces_root / workspace_id / "sessions" / session_id
        return SessionPaths(
            workspace_id=workspace_id,
            session_id=session_id,
            session_dir=session_dir,
            meta=session_dir / "session.json",
            entries=session_dir / "conversation" / "entries.jsonl",
            lanes=session_dir / "conversation" / "lanes.jsonl",
            git_dir=session_dir / "git",
            logs_dir=session_dir / "logs",
        )

    def attach_session(self, workspace_id: str, session_id: str) -> None:
        record = self.require_workspace(workspace_id)
        if session_id in record.session_ids:
            return
        self._begin_mutation(
            "attach_session", workspace_id=workspace_id, session_id=session_id
        )
        for workspace in self._workspaces.values():
            if session_id in workspace.session_ids:
                workspace.session_ids.remove(session_id)
                workspace.updated_at = time.time()
        record.session_ids.insert(0, session_id)
        record.updated_at = time.time()
        self._finish_mutation()

    def detach_session(self, workspace_id: str, session_id: str) -> None:
        record = self.require_workspace(workspace_id)
        if session_id not in record.session_ids:
            return
        self._begin_mutation(
            "detach_session", workspace_id=workspace_id, session_id=session_id
        )
        record.session_ids.remove(session_id)
        record.updated_at = time.time()
        self._finish_mutation()

    def find_session(self, session_id: str) -> Optional[SessionPaths]:
        for workspace in self.list_workspaces():
            if session_id not in workspace.session_ids:
                continue
            paths = self.session_paths(workspace.workspace_id, session_id)
            meta = self.read_session_meta(paths)
            if not meta:
                continue
            if meta.get("workspace_id") != workspace.workspace_id:
                continue
            if _path_key(meta.get("workspace", "")) != _path_key(workspace.path):
                continue
            return paths
        return None

    def read_session_meta(self, paths: SessionPaths) -> dict:
        if not paths.meta.exists():
            return {}
        try:
            payload = json.loads(paths.meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def write_session_meta(self, paths: SessionPaths, payload: dict) -> None:
        paths.ensure()
        _atomic_write_json(paths.meta, payload)

    def session_updated_at(self, paths: SessionPaths) -> float:
        if not paths.session_dir.exists():
            return 0.0
        mtimes = [
            item.stat().st_mtime
            for item in paths.session_dir.rglob("*")
            if item.is_file()
        ]
        return max(mtimes) if mtimes else 0.0

    def delete_session_directory(self, paths: SessionPaths) -> None:
        if not paths.session_dir.exists():
            return
        resolved = paths.session_dir.resolve()
        resolved.relative_to(self.workspaces_root.resolve())
        shutil.rmtree(resolved)

    def write_deletion_journal(self, operation_id: str, payload: dict) -> Path:
        path = self.deletions_root / f"{operation_id}.json"
        _atomic_write_json(path, payload)
        return path

    def migrate_legacy_sessions(self, default_workspace: Path | str) -> int:
        """把已知旧文件复制校验后迁入分级目录，再删除旧副本。"""
        if not self.legacy_sessions_dir.exists():
            return 0
        migrated = 0
        for session_id in sorted(self._legacy_session_ids()):
            if self.find_session(session_id) is not None:
                continue
            legacy_meta = self._read_legacy_meta(session_id)
            workspace_path = legacy_meta.get("workspace") or str(default_workspace)
            try:
                workspace, _ = self.create_workspace(workspace_path)
            except (OSError, ValueError):
                continue
            paths = self.session_paths(workspace.workspace_id, session_id)
            paths.ensure()
            copied: list[tuple[Path, Path]] = []
            try:
                for source, destination in self._legacy_mappings(session_id, paths):
                    if not source.exists():
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    if source.stat().st_size != destination.stat().st_size:
                        raise OSError(f"迁移校验失败: {source}")
                    copied.append((source, destination))
                now = time.time()
                self.write_session_meta(
                    paths,
                    {
                        **legacy_meta,
                        "session_id": session_id,
                        "workspace_id": workspace.workspace_id,
                        "workspace": workspace.path,
                        "title": legacy_meta.get("title") or session_id,
                        "created_at": float(legacy_meta.get("created_at", now)),
                        "updated_at": now,
                    },
                )
                self.attach_session(workspace.workspace_id, session_id)
                for source, _ in copied:
                    source.unlink(missing_ok=True)
                legacy_meta_path = self.legacy_sessions_dir / f"{session_id}_meta.json"
                legacy_meta_path.unlink(missing_ok=True)
                migrated += 1
            except OSError:
                if not self.read_session_meta(paths):
                    shutil.rmtree(paths.session_dir, ignore_errors=True)
        return migrated

    def _legacy_session_ids(self) -> set[str]:
        result: set[str] = set()
        for path in self.legacy_sessions_dir.glob("*.jsonl"):
            result.add(path.stem.removesuffix("_lanes"))
        for suffix in (
            "_meta.json",
            "_git_bindings.json",
            "_checkpoints.ndjson",
            "_operations.ndjson",
        ):
            for path in self.legacy_sessions_dir.glob(f"*{suffix}"):
                result.add(path.name.removesuffix(suffix))
        return result

    def _read_legacy_meta(self, session_id: str) -> dict:
        path = self.legacy_sessions_dir / f"{session_id}_meta.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _legacy_mappings(
        self, session_id: str, paths: SessionPaths
    ) -> Iterable[tuple[Path, Path]]:
        root = self.legacy_sessions_dir
        return (
            (root / f"{session_id}.jsonl", paths.entries),
            (root / f"{session_id}_lanes.jsonl", paths.lanes),
            (root / f"{session_id}_git_bindings.json", paths.git_bindings),
            (root / f"{session_id}_checkpoints.ndjson", paths.checkpoints),
            (root / f"{session_id}_operations.ndjson", paths.operations),
        )

    def _reconcile_sessions(self) -> None:
        for workspace in self._workspaces.values():
            valid: list[str] = []
            for session_id in workspace.session_ids:
                paths = self.session_paths(workspace.workspace_id, session_id)
                meta = self.read_session_meta(paths)
                if (
                    meta.get("workspace_id") == workspace.workspace_id
                    and _path_key(meta.get("workspace", "")) == _path_key(workspace.path)
                ):
                    valid.append(session_id)
            workspace.session_ids = valid
        self._pending_mutation = None
        self._save()
