"""Lane 分支指针管理。

对应功能设计 03-Lane分支管理系统、12-存储层设计 5.3/6.2 节。

物理文件是 append-only 流水（同名 lane 会出现多次），内存态是**重放全部行**后的
最新快照。加载时不能只读最后一行——文件物理上的最后一行可能是另一个 lane 刚被
更新产生的（12 号文档 6.2 节）。

Lane 只是指向叶子节点的指针，不携带路径信息；拿掉所有 Lane，树依然完整
（03 号文档 1.5.1 节）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from ..errors.types import (
    CODE_INVALID_LANE_NAME,
    CODE_LANE_EXISTS,
    CODE_LANE_NOT_FOUND,
    CODE_LANE_PROTECTED,
    AgentError,
    LaneNotFoundError,
    ValidationError,
)
from .models import LanePointer

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data/sessions")

MAIN_LANE = "main"

# kebab-case：小写字母/数字，用单个短横线分隔（03 号文档 5.2 节的命名规范）
LANE_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LANE_NAME_MAX_LENGTH = 64


def validate_lane_name(name: str) -> None:
    """校验分支名，不合法则抛 ValidationError。

    前端也会做同样的即时校验（07 号文档 7.3 节），但后端必须独立校验——
    前端校验只是交互体验，不能当作安全边界。
    """
    if not name:
        raise ValidationError(
            message="分支名不能为空",
            code=CODE_INVALID_LANE_NAME,
            validation_errors=["分支名不能为空"],
        )
    if len(name) > LANE_NAME_MAX_LENGTH:
        raise ValidationError(
            message=f"分支名过长（上限 {LANE_NAME_MAX_LENGTH} 字符）",
            code=CODE_INVALID_LANE_NAME,
            validation_errors=[f"当前长度 {len(name)}"],
        )
    if not LANE_NAME_PATTERN.match(name):
        raise ValidationError(
            message=f"分支名不符合 kebab-case 规范: {name}",
            code=CODE_INVALID_LANE_NAME,
            validation_errors=["只允许小写字母、数字和单个短横线分隔，例如 cache-v1"],
            suggestions=["改用 kebab-case，如 algo-approach、bug-fix-auth"],
        )


class LaneManager:
    """Lane 指针管理：append-only 流水 + 重放取最新。"""

    def __init__(
        self, session_id: str, data_dir: Path | str = DEFAULT_DATA_DIR
    ) -> None:
        self.session_id = session_id
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / f"{session_id}_lanes.jsonl"
        self._lanes: dict[str, LanePointer] = {}
        # 当前活跃分支。功能设计文档没规定它存哪儿，这里跟 Lane 流水存一起
        # （写一条 {"current_lane": ...} 记录），这样重启后能回到用户离开时的分支。
        self._current_lane: str = MAIN_LANE

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load()

        # 每个 session 至少有 main 分支。新建 session 时 leaf_id 为 None——
        # 此时树还是空的，第一条消息 append 后才有落脚点。
        if MAIN_LANE not in self._lanes:
            self._append(
                LanePointer(lane=MAIN_LANE, leaf_id=None, seq=1, description="主分支")
            )

    # --- 加载 ---------------------------------------------------------------

    def _load(self) -> None:
        """重放全部行，同名 lane 以最后一次出现为准（12 号文档 6.2 节）。"""
        if not self.path.exists():
            return

        skipped = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    skipped += 1
                    logger.warning("跳过损坏的 Lane 行 #%d: %s", lineno, exc)
                    continue

                # 活跃分支记录，同样靠重放取最后一次
                if "current_lane" in record:
                    self._current_lane = record["current_lane"]
                    continue

                lane = record.get("lane")
                if not lane:
                    skipped += 1
                    logger.warning("跳过缺少 lane 字段的行 #%d", lineno)
                    continue

                # 删除墓碑记录：文件是 append-only，删除不能靠"不写"表达，
                # 必须显式写一条墓碑，否则重放时被删的分支会复活。
                if record.get("deleted"):
                    self._lanes.pop(lane, None)
                    continue

                try:
                    pointer = LanePointer.from_jsonl_dict(record)
                except (KeyError, ValueError, TypeError) as exc:
                    skipped += 1
                    logger.warning("跳过字段非法的 Lane 行 #%d: %s", lineno, exc)
                    continue
                # dict 赋值天然实现"同名覆盖，取最后一次"
                self._lanes[lane] = pointer

        if skipped:
            logger.warning(
                "session %s 的 Lane 文件跳过 %d 行损坏数据", self.session_id, skipped
            )

        # 活跃分支可能已被删除（墓碑在它后面），退回 main
        if self._current_lane not in self._lanes and self._current_lane != MAIN_LANE:
            logger.warning("活跃分支 %s 已不存在，退回 main", self._current_lane)
            self._current_lane = MAIN_LANE

    # --- 活跃分支 -----------------------------------------------------------

    @property
    def current_lane(self) -> str:
        return self._current_lane

    def switch_lane(self, name: str) -> LanePointer:
        """切换活跃分支。

        调用方（SessionRuntime）负责保证没有 run 正在执行——03 号文档 7.3 节
        要求执行期间拒绝切换，那个判断在 run 锁那一层做，不在这里重复。
        """
        pointer = self.get_lane(name)
        if name != self._current_lane:
            self._current_lane = name
            self._append_raw({"current_lane": name})
        return pointer

    # --- 核心操作 -----------------------------------------------------------

    def validate_new_lane(self, name: str) -> None:
        """Validate a Lane before related external resources are created."""
        validate_lane_name(name)
        if name in self._lanes:
            raise AgentError(
                message=f"分支已存在: {name}",
                code=CODE_LANE_EXISTS,
                suggestions=["换一个分支名，或先切换到该分支"],
            )

    def create_lane(
        self, name: str, from_id: Optional[str], description: str = ""
    ) -> LanePointer:
        """从指定节点创建新分支（03 号文档 3.1 节）。

        新分支的 ``leaf_id`` 就是分叉点本身——此时它和源分支路径完全重合，
        直到在新分支上追加第一条消息才真正分叉。
        """
        self.validate_new_lane(name)
        pointer = LanePointer(
            lane=name,
            leaf_id=from_id,
            seq=1,
            created_from=from_id,
            description=description,
        )
        self._append(pointer)
        return pointer

    def update_lane(self, name: str, leaf_id: str) -> LanePointer:
        """把分支指针移到新的叶子节点。每次追加消息后调用。"""
        prev = self._lanes.get(name)
        if prev is None:
            raise LaneNotFoundError(
                message=f"分支不存在: {name}", code=CODE_LANE_NOT_FOUND, lane=name
            )
        pointer = LanePointer(
            lane=name,
            leaf_id=leaf_id,
            seq=prev.seq + 1,
            created_from=prev.created_from,
            description=prev.description,
        )
        self._append(pointer)
        return pointer

    def get_lane(self, name: str) -> LanePointer:
        pointer = self._lanes.get(name)
        if pointer is None:
            raise LaneNotFoundError(
                message=f"分支不存在: {name}",
                code=CODE_LANE_NOT_FOUND,
                lane=name,
                suggestions=["调用 GET /lanes 查看当前所有分支"],
            )
        return pointer

    def has_lane(self, name: str) -> bool:
        return name in self._lanes

    def list_lanes(self) -> list[LanePointer]:
        """按创建顺序（seq=1 的时间戳）返回，前端据此固定分配分类色。

        07 号文档 3.1 节要求"按 Lane 创建顺序固定分配颜色，不循环复用"，
        所以这里的顺序必须稳定——用当前记录的 timestamp 排序是不行的
        （update 会刷新它），得用 created_from 那次的时间。但 append-only 文件里
        最早那条记录已被覆盖，所以退化为按 lane 名的插入顺序（dict 保序），
        main 永远排第一。
        """
        lanes = list(self._lanes.values())
        lanes.sort(key=lambda p: (p.lane != MAIN_LANE,))
        return lanes

    def delete_lane(self, name: str, current_lane: Optional[str] = None) -> None:
        """删除分支指针，不删树中的节点（03 号文档 3.4 节）。"""
        current_lane = current_lane or self._current_lane
        if name == MAIN_LANE:
            raise AgentError(
                message="不能删除 main 分支", code=CODE_LANE_PROTECTED
            )
        if name == current_lane:
            raise AgentError(
                message=f"不能删除当前正在使用的分支: {name}",
                code=CODE_LANE_PROTECTED,
                suggestions=["先切换到别的分支，再删除这个分支"],
            )
        if name not in self._lanes:
            raise LaneNotFoundError(
                message=f"分支不存在: {name}", code=CODE_LANE_NOT_FOUND, lane=name
            )

        del self._lanes[name]
        # 写墓碑，保证重启后不复活
        self._append_raw({"lane": name, "deleted": True})

    # --- 对比 ---------------------------------------------------------------

    def compare_lanes(self, lane_a: str, lane_b: str, storage) -> dict:
        """对比两个分支（03 号文档 4.1 节）。

        返回六个键：``common_ancestor`` / ``lane_a_diff`` / ``lane_b_diff`` /
        ``lane_a_entries`` / ``lane_b_entries`` / ``identical``。diff 列表是 root→leaf 顺序，
        **不含公共祖先本身**。

        边界情况（03 号文档 1.5.4 节）：如果两个 Lane 指向同一个叶子，路径完全
        重合，两个 diff 都是空——调用方应当直接显示"两个分支尚无差异"，
        而不是渲染两列空白。
        """
        leaf_a = self.get_lane(lane_a).leaf_id
        leaf_b = self.get_lane(lane_b).leaf_id

        # 任一分支还没有落脚点（刚建的空 session），谈不上差异
        if leaf_a is None or leaf_b is None:
            return {
                "common_ancestor": None,
                "lane_a_diff": [],
                "lane_b_diff": [],
                "lane_a_entries": [],
                "lane_b_entries": [],
                "identical": True,
            }

        # 两个 Lane 指向同一叶子，路径完全重合
        if leaf_a == leaf_b:
            return {
                "common_ancestor": leaf_a,
                "lane_a_diff": [],
                "lane_b_diff": [],
                "lane_a_entries": [],
                "lane_b_entries": [],
                "identical": True,
            }

        ancestor = storage.find_common_ancestor(leaf_a, leaf_b)
        path_a = storage.get_history_path(leaf_a)
        path_b = storage.get_history_path(leaf_b)

        def tail_after(path: list, ancestor_id: Optional[str]) -> list:
            if ancestor_id is None:
                return path
            for index, entry in enumerate(path):
                if entry.id == ancestor_id:
                    return path[index + 1 :]
            return path

        diff_a = tail_after(path_a, ancestor)
        diff_b = tail_after(path_b, ancestor)

        identical = len(diff_a) == 0 and len(diff_b) == 0

        return {
            "common_ancestor": ancestor,
            "lane_a_diff": [e.id for e in diff_a],
            "lane_b_diff": [e.id for e in diff_b],
            "lane_a_entries": diff_a,
            "lane_b_entries": diff_b,
            "identical": identical,
        }

    # --- 写入 ---------------------------------------------------------------

    def _append(self, pointer: LanePointer) -> None:
        self._lanes[pointer.lane] = pointer
        self._append_raw(pointer.to_jsonl_dict())

    def _append_raw(self, record: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    def delete_files(self) -> None:
        self.path.unlink(missing_ok=True)
