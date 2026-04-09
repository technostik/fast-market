from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from common import structlog
from common.core.config import load_common_config
from common.core.paths import get_common_config_path
from core.security import _assert_path_safe

logger = structlog.get_logger(__name__)

router = APIRouter()


class FileUpdateRequest(BaseModel):
    content: str


def _roots() -> dict[str, Path | None]:
    common_config = load_common_config()
    workdir = common_config.get("workdir")
    workdir_path = Path(workdir).expanduser().resolve() if workdir else None
    return {
        "config": get_common_config_path().parent,
        "data": get_common_config_path().parent.parent,
        "workdir": workdir_path,
    }


def _language_from_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix == ".md":
        return "markdown"
    if suffix in {".sh", ".bash"}:
        return "shell"
    return "text"


def _tree(path: Path, depth: int = 0, max_depth: int = 6) -> dict:
    node_type = "dir" if path.is_dir() else "file"
    node = {"name": path.name or str(path), "path": str(path), "type": node_type}

    if not path.is_dir() or depth >= max_depth:
        return node

    children = []
    for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.is_symlink():
            continue
        children.append(_tree(child, depth=depth + 1, max_depth=max_depth))

    node["children"] = children
    return node


@router.get("/roots")
def roots() -> dict[str, str | None]:
    roots_map = _roots()
    response = {name: (str(path) if path else None) for name, path in roots_map.items()}
    logger.info("fileviewer_roots", roots=response)
    return response


@router.get("/tree")
def tree(root: str = Query(..., pattern="^(config|data|workdir)$")) -> dict:
    roots_map = _roots()
    target = roots_map.get(root)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Root not configured: {root}")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Root path missing: {target}")

    logger.info("fileviewer_tree", root=root, path=str(target))
    return _tree(target)


@router.get("/file")
def get_file(path: str = Query(...)) -> dict[str, str]:
    file_path = Path(path).expanduser().resolve()
    roots_list = [p for p in _roots().values() if p is not None]
    _assert_path_safe(file_path, roots_list)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    logger.info("fileviewer_read_file", path=str(file_path))
    return {
        "content": file_path.read_text(encoding="utf-8"),
        "language": _language_from_suffix(file_path),
    }


@router.put("/file")
def put_file(payload: FileUpdateRequest, path: str = Query(...)) -> dict[str, str | bool]:
    file_path = Path(path).expanduser().resolve()
    roots_list = [p for p in _roots().values() if p is not None]
    _assert_path_safe(file_path, roots_list)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    backup = file_path.with_name(f"{file_path.name}.bak")
    backup.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
    file_path.write_text(payload.content, encoding="utf-8")

    logger.info("fileviewer_save_file", path=str(file_path), backup=str(backup))
    return {"saved": True, "backup": str(backup)}


@router.post("/undo")
def undo_file(path: str = Query(...)) -> dict[str, bool]:
    file_path = Path(path).expanduser().resolve()
    roots_list = [p for p in _roots().values() if p is not None]
    _assert_path_safe(file_path, roots_list)

    backup = file_path.with_name(f"{file_path.name}.bak")
    if not backup.exists() or not backup.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")

    file_path.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
    logger.info("fileviewer_undo_file", path=str(file_path), backup=str(backup))
    return {"restored": True}
