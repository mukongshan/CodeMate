"""当前 Lane 工作区的文件浏览、文本读取与安全保存。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException

MAX_VIEW_FILE_SIZE = 1024 * 1024
MAX_DIRECTORY_ENTRIES = 500
_ENCODING_CANDIDATES = ("utf-8", "utf-8-sig", "gbk", "latin-1")


def _path_error(message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


def _relative_path(path: Path, workspace: Path) -> str:
    relative = path.relative_to(workspace)
    return relative.as_posix() if str(relative) != "." else ""


def _revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve_inside_workspace(workspace: Path | str, relative_path: str) -> tuple[Path, Path]:
    root = Path(workspace).expanduser().resolve()
    requested = (relative_path or "").strip()
    candidate = Path(requested).expanduser()
    if candidate.is_absolute():
        target = candidate.resolve(strict=False)
    else:
        target = (root / candidate).resolve(strict=False)

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise _path_error("路径超出当前工作区范围") from exc
    return root, target


def _is_safe_entry(path: Path, workspace: Path) -> bool:
    if ".git" in path.parts:
        return False
    try:
        path.resolve(strict=False).relative_to(workspace)
    except ValueError:
        return False
    return True


def list_directory(workspace: Path | str, relative_path: str = "") -> dict:
    root, directory = _resolve_inside_workspace(workspace, relative_path)
    if not directory.exists():
        raise _path_error("目录不存在", 404)
    if not directory.is_dir():
        raise _path_error("指定路径不是目录", 400)

    entries: list[dict] = []
    try:
        children = sorted(
            (child for child in directory.iterdir() if _is_safe_entry(child, root)),
            key=lambda child: (not child.is_dir(), child.name.casefold()),
        )
        truncated = len(children) > MAX_DIRECTORY_ENTRIES
        for child in children[:MAX_DIRECTORY_ENTRIES]:
            try:
                stat = child.stat()
            except OSError:
                continue
            is_directory = child.is_dir()
            entries.append(
                {
                    "name": child.name,
                    "path": _relative_path(child, root),
                    "kind": "directory" if is_directory else "file",
                    "size": None if is_directory else stat.st_size,
                    "modified_at": stat.st_mtime,
                    "hidden": child.name.startswith("."),
                }
            )
    except OSError as exc:
        raise _path_error(f"读取目录失败: {exc}", 500) from exc

    return {
        "path": _relative_path(directory, root),
        "entries": entries,
        "truncated": truncated,
        "workspace": str(root),
    }


def _decode(raw: bytes) -> tuple[str | None, str | None]:
    for encoding in _ENCODING_CANDIDATES:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def read_file(workspace: Path | str, relative_path: str = "") -> dict:
    root, file_path = _resolve_inside_workspace(workspace, relative_path)
    if ".git" in file_path.relative_to(root).parts:
        raise _path_error("不允许查看 Git 元数据", 403)
    if not file_path.exists():
        raise _path_error("文件不存在", 404)
    if file_path.is_dir():
        raise _path_error("指定路径是目录，请先展开目录", 400)

    try:
        size = file_path.stat().st_size
        if size > MAX_VIEW_FILE_SIZE:
            raise _path_error(
                f"文件过大，暂不支持查看超过 {MAX_VIEW_FILE_SIZE // 1024} KB 的文件",
                413,
            )
        raw = file_path.read_bytes()
    except HTTPException:
        raise
    except OSError as exc:
        raise _path_error(f"读取文件失败: {exc}", 500) from exc

    if b"\x00" in raw[:8192]:
        return {
            "path": _relative_path(file_path, root),
            "content": None,
            "encoding": None,
            "binary": True,
            "size": size,
            "lines": None,
            "revision": _revision(raw),
            "workspace": str(root),
        }

    content, encoding = _decode(raw)
    if content is None:
        return {
            "path": _relative_path(file_path, root),
            "content": None,
            "encoding": None,
            "binary": True,
            "size": size,
            "lines": None,
            "revision": _revision(raw),
            "workspace": str(root),
        }

    return {
        "path": _relative_path(file_path, root),
        "content": content,
        "encoding": encoding,
        "binary": False,
        "size": size,
        "lines": len(content.splitlines()),
        "revision": _revision(raw),
        "workspace": str(root),
    }


def write_file(
    workspace: Path | str,
    relative_path: str,
    content: str,
    encoding: str | None = None,
    expected_revision: str | None = None,
) -> dict:
    """安全地写入当前 Lane 中已有的文本文件，并检查读取版本。"""
    root, file_path = _resolve_inside_workspace(workspace, relative_path)
    relative = file_path.relative_to(root)
    if not relative.parts or ".git" in relative.parts:
        raise _path_error("不允许修改 Git 元数据", 403)
    if not file_path.exists():
        raise _path_error("文件不存在，当前版本不支持通过编辑器新建文件", 404)
    if file_path.is_dir():
        raise _path_error("指定路径是目录，请先选择文件", 400)

    selected_encoding = (encoding or "utf-8").lower()
    if selected_encoding not in _ENCODING_CANDIDATES:
        raise _path_error(f"不支持的文件编码: {selected_encoding}", 400)
    try:
        raw = content.encode(selected_encoding)
    except UnicodeEncodeError as exc:
        raise _path_error(f"文件内容无法使用 {selected_encoding} 编码保存", 400) from exc
    if len(raw) > MAX_VIEW_FILE_SIZE:
        raise _path_error(
            f"文件过大，暂不支持保存超过 {MAX_VIEW_FILE_SIZE // 1024} KB 的文件",
            413,
        )

    try:
        current_raw = file_path.read_bytes()
    except OSError as exc:
        raise _path_error(f"读取文件版本失败: {exc}", 500) from exc
    current_revision = _revision(current_raw)
    if b"\x00" in current_raw[:8192]:
        raise _path_error("二进制文件不支持通过文本编辑器保存", 400)
    if expected_revision and expected_revision != current_revision:
        raise HTTPException(
            status_code=409,
            detail="文件已被外部修改，请重新加载后再保存",
        )

    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".codemate-tmp", delete=False
        ) as temporary:
            temporary.write(raw)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        try:
            os.chmod(temporary_path, file_path.stat().st_mode)
        except OSError:
            pass
        os.replace(temporary_path, file_path)
        temporary_path = None
    except OSError as exc:
        raise _path_error(f"保存文件失败: {exc}", 500) from exc
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass

    return read_file(root, relative.as_posix())


def restore_file(
    workspace: Path | str,
    relative_path: str,
    before: bytes,
    before_exists: bool,
    expected_revision: str,
) -> dict:
    """恢复一次文件修改，并拒绝覆盖修改后的新版本。"""
    root, file_path = _resolve_inside_workspace(workspace, relative_path)
    relative = file_path.relative_to(root)
    if not relative.parts or ".git" in relative.parts:
        raise _path_error("不允许修改 Git 元数据", 403)
    if not file_path.exists() or file_path.is_dir():
        raise _path_error("待回滚文件不存在或不是文件", 409)

    try:
        current_raw = file_path.read_bytes()
    except OSError as exc:
        raise _path_error(f"读取待回滚文件失败: {exc}", 500) from exc
    if _revision(current_raw) != expected_revision:
        raise _path_error("文件在审查期间已被再次修改，未执行回滚", 409)

    if not before_exists:
        try:
            file_path.unlink()
        except OSError as exc:
            raise _path_error(f"删除新建文件失败: {exc}", 500) from exc
        return {"path": relative.as_posix(), "exists": False}

    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".codemate-rollback", delete=False
        ) as temporary:
            temporary.write(before)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        try:
            os.chmod(temporary_path, file_path.stat().st_mode)
        except OSError:
            pass
        os.replace(temporary_path, file_path)
        temporary_path = None
    except OSError as exc:
        raise _path_error(f"恢复文件失败: {exc}", 500) from exc
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass

    return read_file(root, relative.as_posix())
