"""工作区注册表、Session 分级路径与旧扁平数据迁移。"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


REGISTRY_VERSION = 1
logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            self._recover_corrupt_registry(exc)
            return
        self._apply_payload(payload)

    def _apply_payload(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("工作区注册表必须是 JSON 对象")
        if int(payload.get("version", 0)) != REGISTRY_VERSION:
            raise ValueError("不支持的工作区注册表版本")
        records = payload.get("workspaces", {})
        if not isinstance(records, dict):
            raise ValueError("工作区注册表的 workspaces 字段无效")
        workspaces = {
            str(workspace_id): WorkspaceRecord.from_dict(record)
            for workspace_id, record in records.items()
        }
        raw_order = payload.get("workspace_order", [])
        if not isinstance(raw_order, list):
            raise ValueError("工作区注册表的 workspace_order 字段无效")
        workspace_order = [
            str(workspace_id)
            for workspace_id in raw_order
            if str(workspace_id) in workspaces
        ]
        for workspace_id in workspaces:
            if workspace_id not in workspace_order:
                workspace_order.append(workspace_id)
        pending = payload.get("pending_mutation")
        self._workspaces = workspaces
        self._workspace_order = workspace_order
        self._pending_mutation = pending if isinstance(pending, dict) else None
        if self._pending_mutation is not None:
            self._reconcile_sessions()

    def _recover_corrupt_registry(self, error: json.JSONDecodeError) -> None:
        backup_name = (
            "registry.corrupt-"
            f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
        )
        backup = self.registry_path.with_name(backup_name)
        shutil.copy2(self.registry_path, backup)

        for temporary in sorted(
            self.workspaces_root.glob(f".{self.registry_path.name}.*.tmp"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                payload = json.loads(temporary.read_text(encoding="utf-8"))
                self._apply_payload(payload)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            self._save()
            logger.warning(
                "工作区注册表损坏，已备份到 %s 并从临时文件 %s 恢复",
                backup,
                temporary,
            )
            return

        recovered_sessions = self._rebuild_from_session_metadata()
        self._save()
        logger.warning(
            "工作区注册表损坏（%s），已备份到 %s；从分级目录恢复 %d 个会话",
            error,
            backup,
            recovered_sessions,
        )

    def _rebuild_from_session_metadata(self) -> int:
        recovered: dict[str, tuple[WorkspaceRecord, list[tuple[str, float]]]] = {}
        for meta_path in self.workspaces_root.glob("*/sessions/*/session.json"):
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("跳过无法读取的会话元数据: %s", meta_path)
                continue
            if not isinstance(payload, dict):
                logger.warning("跳过格式无效的会话元数据: %s", meta_path)
                continue

            directory_workspace_id = meta_path.parents[2].name
            directory_session_id = meta_path.parent.name
            workspace_id = str(payload.get("workspace_id") or "")
            session_id = str(payload.get("session_id") or "")
            workspace_path = str(payload.get("workspace") or "").strip()
            if (
                workspace_id != directory_workspace_id
                or session_id != directory_session_id
                or not workspace_path
            ):
                logger.warning("跳过目录身份不一致的会话元数据: %s", meta_path)
                continue

            try:
                updated_at = float(payload.get("updated_at", meta_path.stat().st_mtime))
            except (TypeError, ValueError):
                updated_at = meta_path.stat().st_mtime
            try:
                created_at = float(payload.get("created_at", updated_at))
            except (TypeError, ValueError):
                created_at = updated_at

            item = recovered.get(workspace_id)
            if item is None:
                workspace_title = str(
                    payload.get("workspace_title")
                    or Path(workspace_path).name
                    or workspace_path
                )
                record = WorkspaceRecord(
                    workspace_id=workspace_id,
                    path=workspace_path,
                    title=workspace_title,
                    created_at=created_at,
                    updated_at=updated_at,
                )
                sessions: list[tuple[str, float]] = []
                recovered[workspace_id] = (record, sessions)
            else:
                record, sessions = item
                if _path_key(record.path) != _path_key(workspace_path):
                    logger.warning("跳过工作区路径冲突的会话元数据: %s", meta_path)
                    continue
                record.created_at = min(record.created_at, created_at)
                record.updated_at = max(record.updated_at, updated_at)
            sessions.append((session_id, updated_at))

        self._workspaces = {}
        for workspace_id, (record, sessions) in recovered.items():
            record.session_ids = [
                session_id
                for session_id, _ in sorted(
                    sessions, key=lambda item: item[1], reverse=True
                )
            ]
            self._workspaces[workspace_id] = record
        self._workspace_order = [
            record.workspace_id
            for record in sorted(
                self._workspaces.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
        ]
        self._pending_mutation = None
        return sum(len(record.session_ids) for record in self._workspaces.values())

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
        normalized_title = title.strip() if title and title.strip() else None
        record = WorkspaceRecord(
            workspace_id=workspace_id,
            path=str(canonical),
            title=normalized_title or canonical.name or str(canonical),
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
        for session_id in record.session_ids:
            paths = self.session_paths(workspace_id, session_id)
            meta = self.read_session_meta(paths)
            if meta:
                meta["workspace_title"] = normalized
                self.write_session_meta(paths, meta)
        self._save()
        return record

    def remove_workspace(self, workspace_id: str) -> WorkspaceRecord:
        record = self.require_workspace(workspace_id)
        if record.session_ids:
            raise ValueError("工作区仍包含会话，请先删除会话或使用级联删除")
        internal_dir = self.workspaces_root / workspace_id
        if internal_dir.exists():
            resolved = internal_dir.resolve()
            resolved.relative_to(self.workspaces_root.resolve())
            shutil.rmtree(resolved)
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

    def list_deletion_journals(self) -> list[tuple[Path, dict]]:
        if not self.deletions_root.exists():
            return []
        result: list[tuple[Path, dict]] = []
        for path in self.deletions_root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                result.append((path, payload))
        return result

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
                        "workspace_title": workspace.title,
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

    def legacy_migration_plan(self, default_workspace: Path | str) -> list[dict]:
        result: list[dict] = []
        for session_id in sorted(self._legacy_session_ids()):
            if self.find_session(session_id) is not None:
                continue
            meta = self._read_legacy_meta(session_id)
            result.append(
                {
                    "session_id": session_id,
                    "workspace": meta.get("workspace") or str(default_workspace),
                    "title": meta.get("title") or session_id,
                    "files": [
                        str(source)
                        for source, _ in self._legacy_mappings(
                            session_id,
                            self.session_paths("<workspace-id>", session_id),
                        )
                        if source.exists()
                    ],
                }
            )
        return result

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
