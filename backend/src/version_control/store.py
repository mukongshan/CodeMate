from __future__ import annotations

import json
from pathlib import Path

from .models import CodeCheckpoint, LaneCodeBinding


class LaneGitStore:
    def __init__(self, session_id: str, data_dir: Path | str) -> None:
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.binding_path = root / f"{session_id}_git_bindings.json"
        self.checkpoint_path = root / f"{session_id}_checkpoints.ndjson"
        self.operation_path = root / f"{session_id}_operations.ndjson"
        self.bindings: dict[str, LaneCodeBinding] = {}
        self._load()

    def _load(self) -> None:
        if not self.binding_path.exists():
            return
        try:
            payload = json.loads(self.binding_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in payload.get("bindings", []):
            binding = LaneCodeBinding.from_dict(item)
            self.bindings[binding.lane] = binding

    def save_binding(self, binding: LaneCodeBinding) -> None:
        self.bindings[binding.lane] = binding
        payload = {
            "bindings": [item.to_dict() for item in self.bindings.values()]
        }
        temporary = self.binding_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.binding_path)

    def remove_binding(self, lane: str) -> None:
        self.bindings.pop(lane, None)
        payload = {
            "bindings": [item.to_dict() for item in self.bindings.values()]
        }
        temporary = self.binding_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.binding_path)

    def append_checkpoint(self, checkpoint: CodeCheckpoint) -> None:
        with self.checkpoint_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint.to_dict(), ensure_ascii=False) + "\n")

    def list_checkpoints(self, lane: str | None = None) -> list[CodeCheckpoint]:
        if not self.checkpoint_path.exists():
            return []
        result: list[CodeCheckpoint] = []
        try:
            lines = self.checkpoint_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                checkpoint = CodeCheckpoint(**json.loads(line))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if lane is None or checkpoint.lane == lane:
                result.append(checkpoint)
        return result

    def append_operation(self, record: dict) -> None:
        with self.operation_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_operations(self) -> list[dict]:
        if not self.operation_path.exists():
            return []
        try:
            lines = self.operation_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        result: list[dict] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                result.append(record)
        return result

    def pending_operations(self) -> list[dict]:
        latest: dict[str, dict] = {}
        for record in self.list_operations():
            operation_id = record.get("operation_id")
            if operation_id:
                latest[operation_id] = record
        return [
            record
            for record in latest.values()
            if record.get("state") not in {"completed", "failed", "recovered"}
        ]

    def delete_files(self) -> None:
        self.binding_path.unlink(missing_ok=True)
        self.checkpoint_path.unlink(missing_ok=True)
        self.operation_path.unlink(missing_ok=True)
