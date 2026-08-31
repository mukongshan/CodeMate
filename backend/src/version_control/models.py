from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LaneCodeBinding:
    lane: str
    managed_branch: str
    worktree_path: str
    base_commit: str
    head_commit: str
    sync_state: str = "clean"
    last_checkpoint_id: Optional[str] = None
    published_branch: Optional[str] = None
    published_commit: Optional[str] = None
    published_at: Optional[float] = None
    updated_at: float = field(default_factory=time.time)

    @staticmethod
    def from_dict(data: dict) -> "LaneCodeBinding":
        return LaneCodeBinding(
            lane=data["lane"],
            managed_branch=data["managed_branch"],
            worktree_path=data["worktree_path"],
            base_commit=data["base_commit"],
            head_commit=data["head_commit"],
            sync_state=data.get("sync_state", "clean"),
            last_checkpoint_id=data.get("last_checkpoint_id"),
            published_branch=data.get("published_branch"),
            published_commit=data.get("published_commit"),
            published_at=(
                float(data["published_at"])
                if data.get("published_at") is not None
                else None
            ),
            updated_at=float(data.get("updated_at", time.time())),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_api_dict(self, workspace_relative: Path) -> dict:
        worktree = Path(self.worktree_path)
        active_workspace = worktree / workspace_relative
        return {
            "enabled": True,
            "managed_branch": self.managed_branch,
            "worktree_path": str(worktree),
            "workspace": str(active_workspace),
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "short_head": self.head_commit[:8],
            "sync_state": self.sync_state,
            "last_checkpoint_id": self.last_checkpoint_id,
            "published_branch": self.published_branch,
            "published_commit": self.published_commit,
            "published_at": self.published_at,
            "updated_at": self.updated_at,
        }


@dataclass
class CodeCheckpoint:
    lane: str
    commit_sha: str
    previous_commit: Optional[str]
    reason: str
    conversation_entry_id: Optional[str] = None
    run_id: Optional[str] = None
    run_status: Optional[str] = None
    changed_files: list[dict] = field(default_factory=list)
    checkpoint_id: str = field(
        default_factory=lambda: f"cp_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)
