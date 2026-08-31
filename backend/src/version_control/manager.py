from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
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
    ) -> None:
        self.session_id = session_id
        self.source_workspace = Path(source_workspace).expanduser().resolve()
        self.store = LaneGitStore(session_id, data_dir)
        self.worktree_root = Path(worktree_root).expanduser().resolve()
        self.max_file_bytes = max_file_bytes
        self.repository_root: Optional[Path] = None
        self.repository_id: Optional[str] = None
        self.workspace_relative = Path(".")
        self.enabled = False
        self.disabled_reason = "not a Git repository"
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

    def ensure_main_lane(self) -> LaneCodeBinding:
        self._require_enabled()
        existing = self.store.bindings.get("main")
        if existing:
            return self._ensure_binding_workspace(existing)
        base = self._git_output(["rev-parse", "HEAD"], cwd=self.repository_root)
        return self._create_binding("main", base)

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
        source = self.get_binding(source_lane)
        self.checkpoint(source_lane, reason="before_branch")
        source = self.get_binding(source_lane)
        return self._create_binding(lane, source.head_commit)

    def remove_lane(self, lane: str) -> None:
        if not self.enabled:
            return
        binding = self.store.bindings.get(lane)
        if binding is None:
            return
        self.checkpoint(lane, reason="before_delete")
        worktree = Path(binding.worktree_path)
        if worktree.exists():
            self._git(["worktree", "remove", str(worktree)])
        self.store.remove_binding(lane)

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
    ) -> Optional[CodeCheckpoint]:
        if not self.enabled:
            return None
        binding = self.get_binding(lane)
        worktree = Path(binding.worktree_path)
        self._require_consistent(binding)
        changed_paths = self._changed_paths(worktree)
        if not changed_paths:
            binding.sync_state = "clean"
            binding.head_commit = self._git_output(["rev-parse", "HEAD"], cwd=worktree)
            self.store.save_binding(binding)
            return None

        blocked = self._blocked_paths(worktree, changed_paths)
        if blocked:
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

        checkpoint = CodeCheckpoint(
            lane=lane,
            commit_sha="",
            previous_commit=previous,
            reason=reason,
            conversation_entry_id=conversation_entry_id,
            run_id=run_id,
            run_status=run_status,
            changed_files=self._file_status(previous, worktree),
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
        binding.sync_state = "clean"
        binding.updated_at = time.time()
        self.store.append_checkpoint(checkpoint)
        self.store.save_binding(binding)
        return checkpoint

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
            worktree = Path(binding.worktree_path)
            if worktree.exists():
                self._git(["worktree", "remove", str(worktree)])

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
        worktree = Path(binding.worktree_path)
        if worktree.exists():
            return binding
        worktree.parent.mkdir(parents=True, exist_ok=True)
        self._git(["worktree", "prune"], check=False)
        self._git(["worktree", "add", str(worktree), binding.managed_branch])
        binding.worktree_path = str(worktree.resolve())
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
        if branch_head != binding.head_commit or worktree_head != binding.head_commit:
            return "out_of_sync"
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
    ) -> subprocess.CompletedProcess[str]:
        self._require_enabled()
        command = ["git", "-C", str(cwd or self.repository_root), *args]
        result = self._run_raw(command, check=False)
        if check and result.returncode != 0:
            self._raise_git_error(result)
        return result

    @staticmethod
    def _run_raw(
        command: list[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                shell=False,
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
