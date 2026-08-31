"""当前 Lane 工作区的文件浏览与文本读取。"""

from __future__ import annotations

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
            "workspace": str(root),
        }

    return {
        "path": _relative_path(file_path, root),
        "content": content,
        "encoding": encoding,
        "binary": False,
        "size": size,
        "lines": len(content.splitlines()),
        "workspace": str(root),
    }
