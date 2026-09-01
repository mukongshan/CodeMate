from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

from ..errors.types import AgentError
from .models import CodeCheckpoint, LaneCodeBinding
from .store import LaneGitStore


CODE_GIT_OPERATION_FAILED = "GIT_OPERATION_FAILED"
CODE_CHECKPOINT_BLOCKED = "CHECKPOINT_BLOCKED"
_MAX_DIFF_CHARS = 2 * 1024 * 1024

_SENSITIVE_NAMES = {
    ".env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
_SAFE_ENV_SUFFIXES = {".example", ".sample", ".template"}
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


class GitLaneManager:
    """Bind conversation Lanes to managed branches and linked worktrees."""

    def __init__(
        self,
        session_id: str,
        source_workspace: Path | str,
        data_dir: Path | str,
        worktree_root: Path | str,
        max_file_bytes: int,
        checkpoint_merge_window_seconds: float = 300.0,
        checkpoint_max_pending_runs: int = 10,
        checkpoint_max_pending_files: int = 20,
        checkpoint_max_pending_seconds: float = 1800.0,
        session_layout: bool = False,
    ) -> None:
        self.session_id = session_id
        self.source_workspace = Path(source_workspace).expanduser().resolve()
        self.store = LaneGitStore(
            session_id, data_dir, session_layout=session_layout
        )
        self.worktree_root = Path(worktree_root).expanduser().resolve()
        self.max_file_bytes = max_file_bytes
        self.checkpoint_merge_window_seconds = max(0.0, checkpoint_merge_window_seconds)
        self.checkpoint_max_pending_runs = max(1, checkpoint_max_pending_runs)
        self.checkpoint_max_pending_files = max(1, checkpoint_max_pending_files)
        self.checkpoint_max_pending_seconds = max(0.0, checkpoint_max_pending_seconds)
        self.repository_root: Optional[Path] = None
        self.repository_id: Optional[str] = None
        self.workspace_relative = Path(".")
        self.enabled = False
        self.disabled_reason = "not a Git repository"
        self._last_operation_id: Optional[str] = None
        self._initialize_repository()

    def _initialize_repository(self) -> None:
        try:
            result = self._run_raw(
                ["git", "-C", str(self.source_workspace), "rev-parse", "--show-toplevel"],
                check=False,
            )
        except AgentError as exc:
            self.disabled_reason = str(exc)
            return
        if result.returncode != 0:
            return
        root = Path(result.stdout.strip()).resolve()
        head = self._run_raw(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=False,
        )
        if head.returncode != 0:
            self.disabled_reason = "Git repository has no initial commit"
            return

        common_dir = self._run_raw(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"]
        ).stdout.strip()
        common_path = Path(common_dir)
        if not common_path.is_absolute():
            common_path = (root / common_path).resolve()

        self.repository_root = root
        self.repository_id = hashlib.sha256(
            os.path.normcase(str(common_path)).encode("utf-8")
        ).hexdigest()[:16]
        try:
            self.worktree_root.relative_to(root)
        except ValueError:
            pass
        else:
            raise AgentError(
                message="Managed worktree root must be outside the source repository",
                code=CODE_GIT_OPERATION_FAILED,
                details={
                    "repository_root": str(root),
                    "worktree_root": str(self.worktree_root),
                },
            )
        try:
            self.workspace_relative = self.source_workspace.relative_to(root)
        except ValueError:
            self.workspace_relative = Path(".")
        self.enabled = True
        self.disabled_reason = ""
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        self._disabled_hooks_dir().mkdir(parents=True, exist_ok=True)
        self.ensure_main_lane()

    @property
    def last_operation_id(self) -> Optional[str]:
        return self._last_operation_id

    def complete_operation(self, operation_id: Optional[str]) -> None:
        if operation_id:
            self._record_operation(operation_id, "completed")

    def reconcile_operations(self, known_lanes: set[str]) -> list[dict]:
        latest: dict[str, dict] = {}
        metadata: dict[str, dict] = {}
        for record in self.store.list_operations():
            operation_id = record.get("operation_id")
            if operation_id:
                latest[operation_id] = record
                metadata.setdefault(operation_id, {}).update(
                    {
                        key: record[key]
                        for key in ("operation", "lane")
                        if key in record
                    }
                )
        recovered: list[dict] = []
        for operation_id, record in latest.items():
            if record.get("state") in {"completed", "failed", "recovered"}:
                continue
            operation = metadata.get(operation_id, {}).get("operation")
            if operation != "create_lane":
                continue
            lane = str(metadata.get(operation_id, {}).get("lane", ""))
            if lane in known_lanes:
                self._record_operation(operation_id, "recovered", {"action": "kept"})
                recovered.append({"operation_id": operation_id, "lane": lane, "action": "kept"})
            elif lane in self.store.bindings:
                self.rollback_lane_creation(lane)
                self._record_operation(operation_id, "recovered", {"action": "rolled_back"})
                recovered.append({"operation_id": operation_id, "lane": lane, "action": "rolled_back"})
        return recovered

    def ensure_main_lane(self) -> LaneCodeBinding:
        self._require_enabled()
        existing = self.store.bindings.get("main")
        if existing:
            return self._ensure_binding_workspace(existing)
        assert self.repository_root is not None
        head = self._git_output(["rev-parse", "HEAD"], cwd=self.source_workspace)
        binding = LaneCodeBinding(
            lane="main",
            managed_branch=self._source_branch(),
            worktree_path=str(self.repository_root),
            base_commit=head,
            head_commit=head,
        )
        self.store.save_binding(binding)
        return binding

    def ensure_legacy_lane(self, lane: str) -> LaneCodeBinding:
        """Create a binding for a pre-Git Lane using main's current Code Head."""
        existing = self.store.bindings.get(lane)
        if existing:
            return self._ensure_binding_workspace(existing)
        main = self.get_binding("main")
        return self._create_binding(lane, main.head_commit)

    def active_workspace(self, lane: str) -> Path:
        if not self.enabled:
            return self.source_workspace
        binding = self.get_binding(lane)
        if lane == "main":
            return self.source_workspace
        return (Path(binding.worktree_path) / self.workspace_relative).resolve()

    def get_binding(self, lane: str) -> LaneCodeBinding:
        binding = self.store.bindings.get(lane)
        if binding is None:
            raise AgentError(
                message=f"Lane has no Git workspace: {lane}",
                code=CODE_GIT_OPERATION_FAILED,
            )
        return self._ensure_binding_workspace(binding)

    def has_binding(self, lane: str) -> bool:
        return lane in self.store.bindings

    def ensure_lane_ready(self, lane: str) -> None:
        binding = self.get_binding(lane)
        changed_paths = self._changed_paths(Path(binding.worktree_path))
        sync_state = self._sync_state(binding, changed_paths)
        if sync_state in {"out_of_sync", "unavailable"}:
            raise AgentError(
                message=f"Lane Git workspace is {sync_state}: {lane}",
                code=CODE_GIT_OPERATION_FAILED,
                details={"lane": lane, "sync_state": sync_state},
                suggestions=["Restore the managed branch/worktree before continuing"],
            )

    def lane_api(self, lane: str) -> dict:
        if not self.enabled:
            return {"enabled": False, "reason": self.disabled_reason}
        binding = self.store.bindings.get(lane)
        if binding is None:
            return {
                "enabled": True,
                "sync_state": "unavailable",
                "reason": f"Lane has no Git workspace: {lane}",
            }
        payload = binding.to_api_dict(self.workspace_relative)
        try:
            binding = self.get_binding(lane)
            status = self.status(lane)
            binding.sync_state = self._sync_state(binding, status["changed_files"])
            binding.updated_at = time.time()
            self.store.save_binding(binding)
            payload = binding.to_api_dict(self.workspace_relative)
            payload.update(status)
        except AgentError as exc:
            payload.update(
                {
                    "sync_state": "unavailable",
                    "reason": str(exc),
                    "changed_files": [],
                    "blocked_files": [],
                }
            )
        return payload

    def create_lane(self, lane: str, source_lane: str) -> LaneCodeBinding:
        self._require_enabled()
        if lane in self.store.bindings:
            return self.get_binding(lane)
        operation_id = f"op_{uuid.uuid4().hex[:12]}"
        self._last_operation_id = operation_id
        self._record_operation(operation_id, "prepared", {"operation": "create_lane", "lane": lane})
        source = self.get_binding(source_lane)
        try:
            self.checkpoint(source_lane, reason="before_branch")
            self._record_operation(operation_id, "checkpoint_done")
            source = self.get_binding(source_lane)
            binding = self._create_binding(lane, source.head_commit)
            self._record_operation(operation_id, "git_done")
            return binding
        except Exception as exc:
            self._record_operation(operation_id, "failed", {"error": str(exc)})
            raise

    def remove_lane(self, lane: str) -> None:
        if lane == "main":
            raise AgentError(
                message="main Lane 使用用户主目录，不能被删除",
                code=CODE_GIT_OPERATION_FAILED,
            )
        if not self.enabled:
            return
        binding = self.store.bindings.get(lane)
        if binding is None:
            return
        self.checkpoint(lane, reason="before_delete")
        worktree = Path(binding.worktree_path)
        if worktree.exists():
            self._git(["worktree", "remove", str(worktree)])
        self._git(["branch", "-D", binding.managed_branch], check=False)
        self.store.remove_binding(lane)

    def rename_lane(self, lane: str, new_lane: str) -> None:
        if not self.enabled or lane not in self.store.bindings:
            return
        self.store.rename_binding(lane, new_lane)

    def delete_managed_resources(self) -> None:
        if not self.enabled:
            return
        for binding in list(self.store.bindings.values()):
            if binding.lane == "main":
                continue
            self.checkpoint(binding.lane, reason="before_session_delete")
        for binding in list(self.store.bindings.values()):
            if binding.lane == "main":
                continue
            worktree = Path(binding.worktree_path)
            if worktree.exists():
                self._git(["worktree", "remove", str(worktree)])
            self._git(["branch", "-D", binding.managed_branch], check=False)
            self.store.remove_binding(binding.lane)

    def rollback_lane_creation(self, lane: str) -> None:
        """Remove an unpublished worktree/binding after Lane metadata creation fails."""
        if not self.enabled:
            return
        binding = self.store.bindings.get(lane)
        if binding is None:
            return
        worktree = Path(binding.worktree_path)
        if worktree.exists():
            self._git(
                ["worktree", "remove", "--force", str(worktree)], check=False
            )
        self.store.remove_binding(lane)
        self._git(["branch", "-D", binding.managed_branch], check=False)

    def status(self, lane: str) -> dict:
        if not self.enabled:
            return {"changed_files": [], "blocked_files": []}
        binding = self.get_binding(lane)
        worktree = Path(binding.worktree_path)
        changed = self._changed_paths(worktree)
        blocked = self._blocked_paths(worktree, changed)
        return {
            "changed_files": changed,
            "blocked_files": blocked,
        }

    def checkpoint(
        self,
        lane: str,
        *,
        reason: str,
        conversation_entry_id: Optional[str] = None,
        run_id: Optional[str] = None,
        run_status: Optional[str] = None,
        include_paths: Optional[list[str]] = None,
        allow_blocked: bool = False,
    ) -> Optional[CodeCheckpoint]:
        if not self.enabled:
            return None
        binding = self.get_binding(lane)
        worktree = Path(binding.worktree_path)
        self._require_consistent(binding)
        all_changed_paths = self._changed_paths(worktree)
        selected_paths = self._select_paths(all_changed_paths, include_paths)
        if include_paths is not None:
            staged_paths = self._git_output(
                ["diff", "--cached", "--name-only", "-z"], cwd=worktree
            ).split("\0")
            staged_outside_selection = [
                item for item in staged_paths if item and item not in selected_paths
            ]
            if staged_outside_selection:
                raise AgentError(
                    message="Selected checkpoint cannot exclude already staged files",
                    code=CODE_CHECKPOINT_BLOCKED,
                    details={"staged_outside_selection": staged_outside_selection},
                    suggestions=["Unstage those files or include them in the checkpoint"],
                )
        changed_paths = selected_paths
        if not changed_paths:
            if not all_changed_paths:
                self._clear_pending_checkpoint(binding)
            binding.sync_state = "dirty" if all_changed_paths else "clean"
            binding.head_commit = self._git_output(["rev-parse", "HEAD"], cwd=worktree)
            self.store.save_binding(binding)
            return None

        blocked = self._blocked_paths(worktree, changed_paths)
        if blocked and not allow_blocked:
            binding.sync_state = "dirty"
            self.store.save_binding(binding)
            raise AgentError(
                message="Code checkpoint requires confirmation for blocked files",
                code=CODE_CHECKPOINT_BLOCKED,
                details={"blocked_files": blocked, "changed_files": changed_paths},
                suggestions=["Remove, ignore, or explicitly review the blocked files"],
            )

        previous = self._git_output(["rev-parse", "HEAD"], cwd=worktree)
        self._stage_paths(worktree, changed_paths)
        staged = self._git_output(["diff", "--cached", "--name-only", "-z"], cwd=worktree)
        if not staged:
            return None

        pending_run_ids = list(binding.pending_run_ids)
        if run_id and run_id not in pending_run_ids:
            pending_run_ids.append(run_id)
        pending_entry_ids = list(binding.pending_conversation_entry_ids)
        if conversation_entry_id and conversation_entry_id not in pending_entry_ids:
            pending_entry_ids.append(conversation_entry_id)
        checkpoint = CodeCheckpoint(
            lane=lane,
            commit_sha="",
            previous_commit=previous,
            reason=reason,
            conversation_entry_id=conversation_entry_id,
            run_id=run_id or (pending_run_ids[-1] if pending_run_ids else None),
            run_status=run_status,
            changed_files=self._file_status(previous, worktree),
            run_ids=pending_run_ids,
            conversation_entry_ids=pending_entry_ids,
        )
        message = self._checkpoint_message(checkpoint)
        self._git(
            [
                "-c",
                f"core.hooksPath={self._disabled_hooks_dir()}",
                "-c",
                "user.name=CodeMate Checkpoint",
                "-c",
                "user.email=checkpoint@codemate.local",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "--no-verify",
                "-m",
                message,
            ],
            cwd=worktree,
        )
        checkpoint.commit_sha = self._git_output(["rev-parse", "HEAD"], cwd=worktree)
        binding.head_commit = checkpoint.commit_sha
        binding.last_checkpoint_id = checkpoint.checkpoint_id
        remaining_paths = self._changed_paths(worktree)
        binding.sync_state = "dirty" if remaining_paths else "clean"
        if not remaining_paths:
            self._clear_pending_checkpoint(binding)
        binding.updated_at = time.time()
        self.store.append_checkpoint(checkpoint)
        self.store.save_binding(binding)
        return checkpoint

    def defer_run_checkpoint(
        self,
        lane: str,
        *,
        run_id: str,
        conversation_entry_id: Optional[str] = None,
        now: Optional[float] = None,
    ) -> dict:
        """登记一次成功 Run 的待检查点，并判断是否应立即合并提交。"""
        if not self.enabled:
            return {
                "pending": False,
                "should_flush": False,
                "changed_files": [],
                "pending_run_count": 0,
            }
        binding = self.get_binding(lane)
        worktree = Path(binding.worktree_path)
        self._require_consistent(binding)
        current = now if now is not None else time.time()
        changed_files = self._changed_paths(worktree)
        if not changed_files:
            self._clear_pending_checkpoint(binding)
            binding.sync_state = "clean"
            self.store.save_binding(binding)
            return {
                "pending": False,
                "should_flush": False,
                "changed_files": [],
                "pending_run_count": 0,
            }
        if binding.pending_checkpoint_since is None:
            binding.pending_checkpoint_since = current
        binding.pending_checkpoint_last_run_at = current
        if run_id not in binding.pending_run_ids:
            binding.pending_run_ids.append(run_id)
        if conversation_entry_id and conversation_entry_id not in binding.pending_conversation_entry_ids:
            binding.pending_conversation_entry_ids.append(conversation_entry_id)
        binding.sync_state = "dirty"
        binding.updated_at = current
        self.store.save_binding(binding)
        status = self.pending_checkpoint_status(lane, now=current)
        return status

    def pending_checkpoint_status(
        self, lane: str, *, now: Optional[float] = None
    ) -> dict:
        if not self.enabled:
            return {
                "pending": False,
                "should_flush": False,
                "changed_files": [],
                "pending_run_count": 0,
            }
        binding = self.get_binding(lane)
        current = now if now is not None else time.time()
        changed_files = self._changed_paths(Path(binding.worktree_path))
        pending = bool(binding.pending_run_ids or binding.pending_checkpoint_since)
        if not pending:
            return {
                "pending": False,
                "should_flush": False,
                "changed_files": changed_files,
                "pending_run_count": 0,
            }
        since = binding.pending_checkpoint_since or current
        last_run = binding.pending_checkpoint_last_run_at or since
        idle_due = current - last_run >= self.checkpoint_merge_window_seconds
        age_due = current - since >= self.checkpoint_max_pending_seconds
        runs_due = len(binding.pending_run_ids) >= self.checkpoint_max_pending_runs
        files_due = len(changed_files) >= self.checkpoint_max_pending_files
        reasons = []
        if idle_due:
            reasons.append("merge_window_elapsed")
        if age_due:
            reasons.append("max_pending_age")
        if runs_due:
            reasons.append("max_pending_runs")
        if files_due:
            reasons.append("max_pending_files")
        return {
            "pending": True,
            "should_flush": bool(reasons),
            "flush_reasons": reasons,
            "changed_files": changed_files,
            "pending_run_count": len(binding.pending_run_ids),
            "pending_since": since,
            "pending_last_run_at": last_run,
            "next_flush_at": min(
                last_run + self.checkpoint_merge_window_seconds,
                since + self.checkpoint_max_pending_seconds,
            ),
        }

    @staticmethod
    def _clear_pending_checkpoint(binding: LaneCodeBinding) -> None:
        binding.pending_checkpoint_since = None
        binding.pending_checkpoint_last_run_at = None
        binding.pending_run_ids = []
        binding.pending_conversation_entry_ids = []

    def list_checkpoints(self, lane: str) -> list[dict]:
        self.get_binding(lane)
        return [item.to_dict() for item in self.store.list_checkpoints(lane)]

    def restore_checkpoint(
        self, lane: str, checkpoint_id: str, *, discard_changes: bool = False
    ) -> dict:
        binding = self.get_binding(lane)
        checkpoints = self.store.list_checkpoints(lane)
        checkpoint = next(
            (item for item in checkpoints if item.checkpoint_id == checkpoint_id), None
        )
        if checkpoint is None:
            raise AgentError(
                message=f"Checkpoint not found: {checkpoint_id}",
                code=CODE_GIT_OPERATION_FAILED,
            )
        self._require_consistent(binding)
        worktree = Path(binding.worktree_path)
        changed = self._changed_paths(worktree)
        if changed and not discard_changes:
            raise AgentError(
                message="当前 Worktree 有未保存修改，不能直接恢复检查点",
                code=CODE_CHECKPOINT_BLOCKED,
                details={"changed_files": changed},
                suggestions=["先创建检查点，或明确确认放弃当前修改"],
            )
        self._git(["cat-file", "-e", f"{checkpoint.commit_sha}^{{commit}}"])
        self._git(["reset", "--hard", checkpoint.commit_sha], cwd=worktree)
        if discard_changes:
            self._git(["clean", "-fd", "--", "."], cwd=worktree)
        binding.head_commit = checkpoint.commit_sha
        binding.sync_state = "clean"
        binding.updated_at = time.time()
        self.store.save_binding(binding)
        return {
            "lane": lane,
            "checkpoint": checkpoint.to_dict(),
            "discarded_changes": bool(changed and discard_changes),
            "status": self.status(lane),
        }

    def discard_changes(self, lane: str) -> dict:
        binding = self.get_binding(lane)
        self._require_consistent(binding)
        worktree = Path(binding.worktree_path)
        changed = self._changed_paths(worktree)
        self._git(["reset", "--hard", "HEAD"], cwd=worktree)
        self._git(["clean", "-fd", "--", "."], cwd=worktree)
        binding.sync_state = "clean"
        binding.updated_at = time.time()
        self.store.save_binding(binding)
        return {"lane": lane, "discarded_files": changed, "status": self.status(lane)}

    def publish(
        self,
        lane: str,
        target_branch: str,
        *,
        mode: str = "branch",
        base_branch: Optional[str] = None,
    ) -> dict:
        if mode not in {"branch", "squash"}:
            raise AgentError(
                message=f"Unsupported publish mode: {mode}",
                code=CODE_GIT_OPERATION_FAILED,
            )
        binding = self.get_binding(lane)
        self._require_consistent(binding)
        checkpoint = self.checkpoint(lane, reason="before_publish")
        if checkpoint is not None:
            binding = self.get_binding(lane)
        target_branch = target_branch.strip()
        if not target_branch or target_branch.startswith("codemate/"):
            raise AgentError(
                message="发布目标必须是普通 Git 分支名",
                code=CODE_GIT_OPERATION_FAILED,
            )
        if self._git(
            ["check-ref-format", "--branch", target_branch], check=False
        ).returncode != 0:
            raise AgentError(
                message=f"Invalid target Git branch: {target_branch}",
                code=CODE_GIT_OPERATION_FAILED,
            )
        target_exists = self._git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{target_branch}"],
            check=False,
        ).returncode == 0
        if target_exists:
            return self._update_published_branch(
                binding,
                target_branch,
                mode=mode,
                base_branch=base_branch,
            )

        created_branch = False
        publish_worktree: Optional[Path] = None
        published_base_branch: Optional[str] = None
        try:
            if mode == "branch":
                self._git(["branch", target_branch, binding.head_commit])
                created_branch = True
                published_commit = binding.head_commit
            else:
                base_ref = base_branch or self._source_branch()
                published_base_branch = base_ref
                base_commit = self._git_output(["rev-parse", base_ref])
                publish_worktree = self._publish_worktree(target_branch)
                self._git(
                    ["worktree", "add", "-b", target_branch, str(publish_worktree), base_commit]
                )
                created_branch = True
                merge_result = self._git(
                    ["merge", "--squash", "--no-commit", binding.head_commit],
                    cwd=publish_worktree,
                    check=False,
                )
                if merge_result.returncode != 0:
                    self._raise_git_error(merge_result)
                staged = self._git(
                    ["diff", "--cached", "--quiet"],
                    cwd=publish_worktree,
                    check=False,
                )
                if staged.returncode != 0:
                    self._git(
                        [
                            "-c",
                            f"core.hooksPath={self._disabled_hooks_dir()}",
                            "-c",
                            "user.name=CodeMate Publisher",
                            "-c",
                            "user.email=publisher@codemate.local",
                            "-c",
                            "commit.gpgSign=false",
                            "commit",
                            "--no-verify",
                            "-m",
                            f"Adopt CodeMate Lane {lane}",
                        ],
                        cwd=publish_worktree,
                    )
                published_commit = self._git_output(
                    ["rev-parse", "HEAD"], cwd=publish_worktree
                )
        except Exception:
            if publish_worktree is not None:
                self._git(
                    ["worktree", "remove", "--force", str(publish_worktree)],
                    check=False,
                )
            if created_branch:
                self._git(["branch", "-D", target_branch], check=False)
            raise
        finally:
            if publish_worktree is not None and publish_worktree.exists():
                self._git(
                    ["worktree", "remove", "--force", str(publish_worktree)],
                    check=False,
                )

        binding.published_branch = target_branch
        binding.published_commit = published_commit
        binding.published_lane_head = binding.head_commit
        binding.published_mode = mode
        binding.published_base_branch = published_base_branch
        binding.publication_count = 1
        binding.published_at = time.time()
        self.store.save_binding(binding)
        return {
            "lane": lane,
            "mode": mode,
            "action": "created",
            "target_branch": target_branch,
            "published_commit": published_commit,
            "published_lane_head": binding.head_commit,
            "short_commit": published_commit[:8],
            "publication_count": binding.publication_count,
        }

    def _update_published_branch(
        self,
        binding: LaneCodeBinding,
        target_branch: str,
        *,
        mode: str,
        base_branch: Optional[str],
    ) -> dict:
        if binding.published_branch != target_branch or not binding.published_commit:
            raise AgentError(
                message=f"Target Git branch already exists: {target_branch}",
                code=CODE_GIT_OPERATION_FAILED,
                details={
                    "target_branch": target_branch,
                    "published_branch": binding.published_branch,
                },
                suggestions=["换一个目标分支名，避免覆盖不属于当前 Lane 的用户分支"],
            )

        published_mode = binding.published_mode
        previous_lane_head = binding.published_lane_head
        if published_mode is None and mode == "branch":
            # 旧版 branch 发布的目标提交就是当时的 Lane Head，可以安全迁移。
            published_mode = "branch"
            previous_lane_head = previous_lane_head or binding.published_commit
            binding.published_mode = published_mode
            binding.published_lane_head = previous_lane_head
            binding.publication_count = max(binding.publication_count, 1)
            binding.updated_at = time.time()
            self.store.save_binding(binding)
        if published_mode is None or previous_lane_head is None:
            raise AgentError(
                message="旧版发布记录缺少增量基线，不能安全更新原分支",
                code=CODE_GIT_OPERATION_FAILED,
                details={"target_branch": target_branch, "requested_mode": mode},
                suggestions=["使用新的目标分支名重新发布"],
            )
        if published_mode != mode:
            raise AgentError(
                message="不能用不同发布模式更新同一个目标分支",
                code=CODE_GIT_OPERATION_FAILED,
                details={"published_mode": published_mode, "requested_mode": mode},
                suggestions=["保持原发布模式，或使用新的目标分支名"],
            )
        if (
            mode == "squash"
            and base_branch
            and binding.published_base_branch
            and base_branch != binding.published_base_branch
        ):
            raise AgentError(
                message="更新 squash 发布时不能更换基线分支",
                code=CODE_GIT_OPERATION_FAILED,
                details={
                    "published_base_branch": binding.published_base_branch,
                    "requested_base_branch": base_branch,
                },
                suggestions=["沿用原基线，或使用新的目标分支名重新发布"],
            )

        target_head = self._git_output(["rev-parse", target_branch])
        if target_head != binding.published_commit:
            raise AgentError(
                message="已发布分支在 CodeMate 之外发生了变化，不能自动覆盖",
                code=CODE_GIT_OPERATION_FAILED,
                details={
                    "target_branch": target_branch,
                    "recorded_commit": binding.published_commit,
                    "actual_commit": target_head,
                },
                suggestions=["检查外部提交后手动合并，或发布到新的目标分支"],
            )
        if previous_lane_head == binding.head_commit:
            return self._publication_payload(
                binding, target_branch, mode, action="unchanged"
            )
        if not self._is_ancestor(previous_lane_head, binding.head_commit):
            raise AgentError(
                message="Lane 历史已回退或改写，不能安全增量发布",
                code=CODE_GIT_OPERATION_FAILED,
                details={
                    "previous_lane_head": previous_lane_head,
                    "current_lane_head": binding.head_commit,
                },
                suggestions=["使用新的目标分支名重新发布"],
            )

        checked_out_path = self._branch_worktree(target_branch)
        if checked_out_path is not None:
            raise AgentError(
                message=f"目标分支正在工作区中检出，不能后台更新: {target_branch}",
                code=CODE_GIT_OPERATION_FAILED,
                details={"target_branch": target_branch, "worktree": checked_out_path},
                suggestions=["先在对应工作区切换到其他分支，再重试发布"],
            )

        previous_published_commit = binding.published_commit
        if mode == "branch":
            self._git(
                [
                    "update-ref",
                    f"refs/heads/{target_branch}",
                    binding.head_commit,
                    target_head,
                ]
            )
            published_commit = binding.head_commit
        else:
            published_commit = self._publish_squash_increment(
                binding,
                target_branch,
                previous_lane_head,
                target_head,
            )

        binding.published_commit = published_commit
        binding.published_lane_head = binding.head_commit
        binding.published_mode = mode
        binding.publication_count = max(binding.publication_count, 1) + 1
        binding.published_at = time.time()
        self.store.save_binding(binding)
        payload = self._publication_payload(
            binding, target_branch, mode, action="updated"
        )
        payload["previous_published_commit"] = previous_published_commit
        return payload

    def _publish_squash_increment(
        self,
        binding: LaneCodeBinding,
        target_branch: str,
        previous_lane_head: str,
        target_head: str,
    ) -> str:
        patch = self._git_bytes(
            [
                "diff",
                "--binary",
                "--full-index",
                previous_lane_head,
                binding.head_commit,
                "--",
            ]
        ).stdout
        if not patch:
            return target_head

        publish_worktree = self._publish_worktree(target_branch)
        try:
            self._git(["worktree", "add", str(publish_worktree), target_branch])
            self._git_bytes(
                ["apply", "--index", "--3way", "--whitespace=nowarn", "-"],
                cwd=publish_worktree,
                input_bytes=patch,
            )
            staged = self._git(
                ["diff", "--cached", "--quiet"],
                cwd=publish_worktree,
                check=False,
            )
            if staged.returncode == 0:
                return target_head
            self._git(
                [
                    "-c",
                    f"core.hooksPath={self._disabled_hooks_dir()}",
                    "-c",
                    "user.name=CodeMate Publisher",
                    "-c",
                    "user.email=publisher@codemate.local",
                    "-c",
                    "commit.gpgSign=false",
                    "commit",
                    "--no-verify",
                    "-m",
                    f"Update CodeMate Lane {binding.lane}",
                ],
                cwd=publish_worktree,
            )
            return self._git_output(["rev-parse", "HEAD"], cwd=publish_worktree)
        finally:
            if publish_worktree.exists():
                self._git(
                    ["worktree", "remove", "--force", str(publish_worktree)],
                    check=False,
                )

    def _publication_payload(
        self,
        binding: LaneCodeBinding,
        target_branch: str,
        mode: str,
        *,
        action: str,
    ) -> dict:
        assert binding.published_commit is not None
        return {
            "lane": binding.lane,
            "mode": mode,
            "action": action,
            "target_branch": target_branch,
            "published_commit": binding.published_commit,
            "published_lane_head": binding.published_lane_head,
            "short_commit": binding.published_commit[:8],
            "publication_count": binding.publication_count,
        }

    def compare(self, lane_a: str, lane_b: str) -> dict:
        if not self.enabled:
            return {"enabled": False, "reason": self.disabled_reason, "files": []}
        binding_a = self.get_binding(lane_a)
        binding_b = self.get_binding(lane_b)
        merge_base = self._git_output(
            ["merge-base", binding_a.head_commit, binding_b.head_commit]
        )
        files = self._name_status(binding_a.head_commit, binding_b.head_commit)
        status_a = self.status(lane_a)
        status_b = self.status(lane_b)
        return {
            "enabled": True,
            "merge_base": merge_base,
            "identical": binding_a.head_commit == binding_b.head_commit,
            "lane_a": {
                "lane": lane_a,
                "head_commit": binding_a.head_commit,
                "short_head": binding_a.head_commit[:8],
                "managed_branch": binding_a.managed_branch,
                "dirty": bool(status_a["changed_files"]),
                "sync_state": self._sync_state(binding_a, status_a["changed_files"]),
            },
            "lane_b": {
                "lane": lane_b,
                "head_commit": binding_b.head_commit,
                "short_head": binding_b.head_commit[:8],
                "managed_branch": binding_b.managed_branch,
                "dirty": bool(status_b["changed_files"]),
                "sync_state": self._sync_state(binding_b, status_b["changed_files"]),
            },
            "files": files,
        }

    def file_diff(self, lane_a: str, lane_b: str, path: str) -> dict:
        if not self.enabled:
            return {
                "enabled": False,
                "reason": self.disabled_reason,
                "path": path,
                "diff": "",
                "binary": False,
                "truncated": False,
            }
        binding_a = self.get_binding(lane_a)
        binding_b = self.get_binding(lane_b)
        normalized = path.replace("\\", "/").lstrip("/")
        candidate = Path(normalized)
        if (
            not normalized
            or candidate.is_absolute()
            or re.match(r"^[A-Za-z]:", normalized)
            or ".." in candidate.parts
        ):
            raise AgentError(
                message="Invalid diff path", code=CODE_GIT_OPERATION_FAILED
            )
        changed_files = self._name_status(binding_a.head_commit, binding_b.head_commit)
        allowed_paths = {
            item[key]
            for item in changed_files
            for key in ("path", "old_path")
            if item.get(key)
        }
        if normalized not in allowed_paths:
            raise AgentError(
                message=f"File is not part of this Lane comparison: {normalized}",
                code=CODE_GIT_OPERATION_FAILED,
            )
        result = self._git(
            [
                "diff",
                "--no-ext-diff",
                "--unified=3",
                binding_a.head_commit,
                binding_b.head_commit,
                "--",
                normalized,
            ],
            check=False,
        )
        if result.returncode not in (0, 1):
            self._raise_git_error(result)
        full_diff = result.stdout
        truncated = len(full_diff) > _MAX_DIFF_CHARS
        diff = full_diff[:_MAX_DIFF_CHARS]
        if truncated:
            diff += "\n\n[CodeMate: diff truncated at 2 MiB]"
        return {
            "path": normalized,
            "diff": diff,
            "binary": "Binary files" in full_diff or "GIT binary patch" in full_diff,
            "truncated": truncated,
        }

    def close_worktrees(self) -> None:
        if not self.enabled:
            return
        for binding in list(self.store.bindings.values()):
            self.checkpoint(binding.lane, reason="before_session_delete")
        for binding in list(self.store.bindings.values()):
            if binding.lane == "main" or Path(binding.worktree_path).resolve() == self.repository_root:
                continue
            worktree = Path(binding.worktree_path)
            if worktree.exists():
                self._git(["worktree", "remove", str(worktree)])

    def _select_paths(
        self, changed_paths: list[str], include_paths: Optional[list[str]]
    ) -> list[str]:
        if include_paths is None:
            return changed_paths
        normalized = {
            item.replace("\\", "/").lstrip("/") for item in include_paths if item.strip()
        }
        unknown = sorted(normalized - set(changed_paths))
        if unknown:
            raise AgentError(
                message="Checkpoint selection contains unchanged files",
                code=CODE_CHECKPOINT_BLOCKED,
                details={"unchanged_files": unknown},
            )
        return [item for item in changed_paths if item in normalized]

    def _source_branch(self) -> str:
        result = self._git(
            ["symbolic-ref", "--short", "-q", "HEAD"],
            cwd=self.source_workspace,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return "HEAD"

    def _publish_worktree(self, target_branch: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", target_branch).strip("-.")
        path = self.worktree_root / self.repository_id / self.session_id / "publish" / safe
        if path.exists():
            raise AgentError(
                message=f"Publish worktree path already exists: {path}",
                code=CODE_GIT_OPERATION_FAILED,
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _is_ancestor(self, older: str, newer: str) -> bool:
        return self._git(
            ["merge-base", "--is-ancestor", older, newer], check=False
        ).returncode == 0

    def _branch_worktree(self, branch: str) -> Optional[str]:
        current_path: Optional[str] = None
        expected_ref = f"branch refs/heads/{branch}"
        for line in self._git_output(["worktree", "list", "--porcelain"]).splitlines():
            if line.startswith("worktree "):
                current_path = line.removeprefix("worktree ")
            elif line == expected_ref:
                return current_path
            elif not line:
                current_path = None
        return None

    def _record_operation(
        self,
        operation_id: str,
        state: str,
        details: Optional[dict] = None,
    ) -> None:
        payload = {
            "operation_id": operation_id,
            "state": state,
            "timestamp": time.time(),
        }
        if details:
            payload.update(details)
        self.store.append_operation(payload)

    def delete_files(self) -> None:
        self.store.delete_files()

    def _create_binding(self, lane: str, start_point: str) -> LaneCodeBinding:
        branch = self._managed_branch(lane)
        worktree = self._lane_worktree(lane)
        if worktree.exists():
            if any(worktree.iterdir()):
                raise AgentError(
                    message=f"Managed worktree path is not empty: {worktree}",
                    code=CODE_GIT_OPERATION_FAILED,
                )
            worktree.rmdir()
        worktree.parent.mkdir(parents=True, exist_ok=True)
        branch_exists = self._git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            check=False,
        ).returncode == 0
        if branch_exists:
            raise AgentError(
                message=f"Managed Git branch already exists: {branch}",
                code=CODE_GIT_OPERATION_FAILED,
                details={"branch": branch, "lane": lane},
                suggestions=["Use a different Lane name or recover the archived branch"],
            )
        args = ["worktree", "add"]
        args.extend(["-b", branch])
        args.extend([str(worktree), start_point])
        self._git(args)
        head = self._git_output(["rev-parse", "HEAD"], cwd=worktree)
        binding = LaneCodeBinding(
            lane=lane,
            managed_branch=branch,
            worktree_path=str(worktree.resolve()),
            base_commit=start_point,
            head_commit=head,
        )
        self.store.save_binding(binding)
        return binding

    def _ensure_binding_workspace(self, binding: LaneCodeBinding) -> LaneCodeBinding:
        if binding.lane == "main":
            return self._ensure_main_source_binding(binding)
        worktree = Path(binding.worktree_path)
        if worktree.exists():
            return binding
        worktree.parent.mkdir(parents=True, exist_ok=True)
        self._git(["worktree", "prune"], check=False)
        self._git(["worktree", "add", str(worktree), binding.managed_branch])
        binding.worktree_path = str(worktree.resolve())
        self.store.save_binding(binding)
        return binding

    def _ensure_main_source_binding(self, binding: LaneCodeBinding) -> LaneCodeBinding:
        """Use the user's repository worktree for main, with safe legacy migration."""
        assert self.repository_root is not None
        source_root = self.repository_root.resolve()
        current_worktree = Path(binding.worktree_path).expanduser().resolve()
        if current_worktree == source_root:
            return binding

        old_worktree = Path(binding.worktree_path)
        old_changed = self._changed_paths(old_worktree) if old_worktree.exists() else []
        source_changed = self._changed_paths(source_root)
        source_head = self._git_output(["rev-parse", "HEAD"], cwd=self.source_workspace)
        if old_changed or source_changed or binding.head_commit != source_head:
            raise AgentError(
                message="旧版 main Lane 不能自动迁移到用户主目录",
                code=CODE_GIT_OPERATION_FAILED,
                details={
                    "source_workspace": str(self.source_workspace),
                    "managed_worktree": str(old_worktree),
                    "managed_changed_files": old_changed,
                    "source_changed_files": source_changed,
                    "managed_head": binding.head_commit,
                    "source_head": source_head,
                },
                suggestions=[
                    "先在旧的 main Worktree 中创建检查点",
                    "确认用户主目录没有未提交修改后重试",
                ],
            )

        if old_worktree.exists():
            self._git(["worktree", "remove", str(old_worktree)])
        binding.managed_branch = self._source_branch()
        binding.worktree_path = str(source_root)
        binding.head_commit = source_head
        binding.sync_state = "clean"
        binding.updated_at = time.time()
        self.store.save_binding(binding)
        return binding

    def _sync_state(self, binding: LaneCodeBinding, changed_paths: list[str]) -> str:
        try:
            branch_head = self._git_output(["rev-parse", binding.managed_branch])
            worktree_head = self._git_output(
                ["rev-parse", "HEAD"], cwd=Path(binding.worktree_path)
            )
        except AgentError:
            return "unavailable"
        if branch_head != worktree_head:
            return "out_of_sync"
        if branch_head != binding.head_commit:
            # Git 是最终事实来源：用户直接在该 Lane 的 worktree 中提交后，
            # 只要 branch ref 与 worktree HEAD 一致，就吸收这个新检查点。
            # 这样后续 CodeMate 自动提交可以继续沿着同一分支工作；若二者不一致，
            # 仍然保留 out_of_sync，避免覆盖外部的分支移动或 detached HEAD。
            binding.head_commit = branch_head
            binding.updated_at = time.time()
            self.store.save_binding(binding)
        return "dirty" if changed_paths else "clean"

    def _require_consistent(self, binding: LaneCodeBinding) -> None:
        sync_state = self._sync_state(binding, [])
        if sync_state in {"out_of_sync", "unavailable"}:
            binding.sync_state = sync_state
            binding.updated_at = time.time()
            self.store.save_binding(binding)
            raise AgentError(
                message=f"Lane Git state is {sync_state}: {binding.lane}",
                code=CODE_GIT_OPERATION_FAILED,
                details={"lane": binding.lane, "sync_state": sync_state},
                suggestions=["Restore the managed branch/worktree before checkpointing"],
            )

    def _changed_paths(self, worktree: Path) -> list[str]:
        commands = [
            ["diff", "--name-only", "-z"],
            ["diff", "--cached", "--name-only", "-z"],
            ["ls-files", "--others", "--exclude-standard", "-z"],
        ]
        paths: set[str] = set()
        for args in commands:
            raw = self._git_output(args, cwd=worktree)
            paths.update(item for item in raw.split("\0") if item)
        return sorted(paths)

    def _blocked_paths(self, worktree: Path, paths: Iterable[str]) -> list[dict]:
        blocked: list[dict] = []
        for relative in paths:
            path = worktree / relative
            reason = self._blocked_reason(path, relative)
            if reason:
                blocked.append({"path": relative, "reason": reason})
        return blocked

    def _blocked_reason(self, path: Path, relative: str) -> Optional[str]:
        name = path.name.lower()
        lower_parts = {part.lower() for part in Path(relative).parts}
        if name == ".env" or (
            name.startswith(".env.")
            and not any(name.endswith(suffix) for suffix in _SAFE_ENV_SUFFIXES)
        ):
            return "environment file"
        if name in _SENSITIVE_NAMES or path.suffix.lower() in _SENSITIVE_SUFFIXES:
            return "credential or private key file"
        if ".ssh" in lower_parts or ".aws" in lower_parts:
            return "credential directory"
        if path.exists() and path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                return "file cannot be inspected"
            if size > self.max_file_bytes:
                return f"file exceeds {self.max_file_bytes} bytes"
            if size <= 1024 * 1024:
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    return "file cannot be inspected"
                if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
                    return "possible secret content"
        return None

    def _stage_paths(self, worktree: Path, paths: list[str]) -> None:
        if not paths:
            return
        self._git(["add", "--all", "--", *paths], cwd=worktree)

    def _file_status(self, previous: str, worktree: Path) -> list[dict]:
        current_tree = self._git_output(["write-tree"], cwd=worktree)
        return self._name_status(previous, current_tree)

    def _name_status(self, left: str, right: str) -> list[dict]:
        raw = self._git_output(
            ["diff", "--name-status", "-z", "--find-renames", left, right]
        )
        parts = raw.split("\0")
        files: list[dict] = []
        index = 0
        while index < len(parts):
            status = parts[index]
            if not status:
                break
            index += 1
            if status.startswith(("R", "C")):
                if index + 1 >= len(parts):
                    break
                old_path = parts[index]
                path = parts[index + 1]
                index += 2
                files.append(
                    {
                        "status": status[0],
                        "score": status[1:] or None,
                        "old_path": old_path,
                        "path": path,
                    }
                )
            else:
                if index >= len(parts):
                    break
                files.append({"status": status[0], "path": parts[index]})
                index += 1
        return files

    def _checkpoint_message(self, checkpoint: CodeCheckpoint) -> str:
        return "\n".join(
            [
                f"codemate(checkpoint): {checkpoint.reason} on {checkpoint.lane}",
                "",
                f"CodeMate-Checkpoint: {checkpoint.checkpoint_id}",
                f"CodeMate-Session: {self.session_id}",
                f"CodeMate-Lane: {checkpoint.lane}",
                f"CodeMate-Run: {checkpoint.run_id or '-'}",
                f"CodeMate-Entry: {checkpoint.conversation_entry_id or '-'}",
                f"CodeMate-Reason: {checkpoint.reason}",
            ]
        )

    def _managed_branch(self, lane: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", self.session_id).strip("-.")
        safe = safe[:32] or "session"
        suffix = hashlib.sha1(self.session_id.encode("utf-8")).hexdigest()[:8]
        return f"codemate/{safe}-{suffix}/{lane}"

    def _lane_worktree(self, lane: str) -> Path:
        assert self.repository_id is not None
        safe_session = re.sub(
            r"[^A-Za-z0-9._-]+", "-", self.session_id
        ).strip("-.")
        safe_session = safe_session[:48] or "session"
        return self.worktree_root / self.repository_id / safe_session / lane

    def _disabled_hooks_dir(self) -> Path:
        return self.worktree_root / ".disabled-hooks"

    def _require_enabled(self) -> None:
        if not self.enabled or self.repository_root is None:
            raise AgentError(
                message=self.disabled_reason or "Git integration is disabled",
                code=CODE_GIT_OPERATION_FAILED,
            )

    def _git_output(self, args: list[str], cwd: Optional[Path] = None) -> str:
        return self._git(args, cwd=cwd).stdout.rstrip("\r\n")

    def _git(
        self,
        args: list[str],
        cwd: Optional[Path] = None,
        *,
        check: bool = True,
        input_text: Optional[str] = None,
    ) -> subprocess.CompletedProcess[str]:
        self._require_enabled()
        command = ["git", "-C", str(cwd or self.repository_root), *args]
        result = self._run_raw(command, check=False, input_text=input_text)
        if check and result.returncode != 0:
            self._raise_git_error(result)
        return result

    def _git_bytes(
        self,
        args: list[str],
        cwd: Optional[Path] = None,
        *,
        check: bool = True,
        input_bytes: Optional[bytes] = None,
    ) -> subprocess.CompletedProcess[bytes]:
        self._require_enabled()
        command = ["git", "-C", str(cwd or self.repository_root), *args]
        try:
            result = subprocess.run(
                command,
                input=input_bytes,
                capture_output=True,
                shell=False,
            )
        except OSError as exc:
            raise AgentError(
                message=f"Failed to execute Git: {exc}",
                code=CODE_GIT_OPERATION_FAILED,
            ) from exc
        if check and result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            raise AgentError(
                message=stderr or stdout or "Git command failed",
                code=CODE_GIT_OPERATION_FAILED,
                details={"returncode": result.returncode},
            )
        return result

    @staticmethod
    def _run_raw(
        command: list[str], *, check: bool = True, input_text: Optional[str] = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                shell=False,
                input=input_text,
            )
        except OSError as exc:
            raise AgentError(
                message=f"Failed to execute Git: {exc}",
                code=CODE_GIT_OPERATION_FAILED,
            ) from exc
        if check and result.returncode != 0:
            raise AgentError(
                message=result.stderr.strip() or "Git command failed",
                code=CODE_GIT_OPERATION_FAILED,
                details={"command": command, "returncode": result.returncode},
            )
        return result

    @staticmethod
    def _raise_git_error(result: subprocess.CompletedProcess[str]) -> None:
        raise AgentError(
            message=result.stderr.strip() or result.stdout.strip() or "Git command failed",
            code=CODE_GIT_OPERATION_FAILED,
            details={"returncode": result.returncode},
        )
