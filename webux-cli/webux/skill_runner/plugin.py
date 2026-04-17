from __future__ import annotations

import json
from pathlib import Path

import requests
import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from common import structlog
from common.core.config import load_common_config
from common.core.paths import (
    get_common_config_path,
    get_data_dir,
    get_skills_dir,
    get_prompts_dir,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


class FileUpdateRequest(BaseModel):
    content: str


def _roots() -> dict[str, Path | None]:
    common_config = load_common_config()
    workdir = common_config.get("workdir_root") or common_config.get("workdir")
    workdir_path = Path(workdir).expanduser().resolve() if workdir else None
    return {
        "config": get_common_config_path().parent.parent,
        "data": get_data_dir().parent,
        "workdir_root": workdir_path,
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
    logger.info("skill_runner_roots", roots=response)
    return response


@router.get("/plans")
def list_plans(pattern: str = Query(default="*.run.yaml")) -> list[dict]:
    """List YAML plan files in workdir_root matching the glob pattern."""
    roots_map = _roots()
    workdir = roots_map.get("workdir_root")
    if not workdir or not workdir.exists():
        return []

    plans = []
    for f in sorted(workdir.rglob(pattern), key=lambda p: p.name.lower()):
        if f.is_file() and not f.is_symlink():
            plans.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "relative": str(f.relative_to(workdir)),
                }
            )

    return plans


@router.get("/tree")
def tree(root: str = Query(..., pattern="^(config|data|workdir_root)$")) -> dict:
    roots_map = _roots()
    target = roots_map.get(root)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Root not configured: {root}")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Root path missing: {target}")

    logger.info("skill_runner_tree", root=root, path=str(target))
    return _tree(target)


@router.get("/load-plan")
def load_plan(url: str | None = None, path: str | None = None) -> dict:
    """Load a YAML plan from URL or local file."""
    content = None
    resolved_path = None

    if url:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            content = resp.text
            resolved_path = url
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {exc}")
    elif path:
        roots_list = [p for p in _roots().values() if p is not None]
        file_path = Path(path).expanduser().resolve()

        from core.security import _assert_path_safe

        _assert_path_safe(file_path, roots_list)

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        content = file_path.read_text(encoding="utf-8")
        resolved_path = str(file_path)
    else:
        raise HTTPException(
            status_code=400, detail="Either url or path must be provided"
        )

    try:
        data = yaml.safe_load(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="YAML must be a dictionary")

    return {
        "content": content,
        "path": resolved_path,
        "data": data,
    }


def _extract_skills(data: dict) -> list[dict]:
    """Extract skill names from plan and return all files for each skill."""
    if not isinstance(data, dict):
        return []

    skill_names = []
    plan = data.get("plan", [])
    for step in plan:
        if isinstance(step, dict):
            skill_name = step.get("skill")
            if skill_name and skill_name not in skill_names:
                skill_names.append(skill_name)

    skills_dir = get_skills_dir()
    result = []

    for skill_name in skill_names:
        skill_path = skills_dir / skill_name
        if not skill_path.exists() or not skill_path.is_dir():
            continue

        files = []
        for f in sorted(
            skill_path.rglob("*"), key=lambda p: (not p.is_dir(), p.name.lower())
        ):
            if (
                f.is_file()
                and not f.is_symlink()
                and not f.name.startswith(".")
                and ".bak" not in f.name
            ):
                files.append(
                    {
                        "name": f.name,
                        "path": str(f),
                        "relative": str(f.relative_to(skill_path)),
                    }
                )

        if files:
            result.append(
                {
                    "name": skill_name,
                    "path": str(skill_path),
                    "files": files,
                }
            )

    return result


@router.get("/skills-from-plan")
def skills_from_plan(plan_content: str = Query(...)) -> list[dict]:
    """Extract skill names from plan content and return all files for each skill."""
    try:
        data = yaml.safe_load(plan_content)
    except Exception:
        return []
    return _extract_skills(data)


@router.get("/skills-from-plan-path")
def skills_from_plan_path(path: str = Query(...)) -> list[dict]:
    """Extract skill names from plan file path and return all files for each skill."""
    roots_list = [p for p in _roots().values() if p is not None]
    file_path = Path(path).expanduser().resolve()

    from core.security import _assert_path_safe

    _assert_path_safe(file_path, roots_list)

    if not file_path.exists() or not file_path.is_file():
        return []

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    return _extract_skills(data)


class SkillsData(BaseModel):
    skills: list[dict]


@router.get("/prompt-names")
def get_prompt_names() -> list[str]:
    """Get all prompt names with filenames from the prompts directory (name:filename)."""
    try:
        from common.core.paths import get_prompts_dir

        prompts_dir = get_prompts_dir()
        if not prompts_dir.exists():
            return []
        results = []
        for f in sorted(prompts_dir.glob("*.md")):
            results.append(f"{f.stem}:{f.name}")
        return results
    except Exception as e:
        logger.warning("prompt_names_failed", error=str(e))
        return []


def _detect_prompts_in_skills(skills_data: list[dict]) -> list[dict]:
    """Detect prompts referenced in skill files by matching prompt names and filenames."""
    try:
        from common.core.paths import get_prompts_dir

        prompts_dir = get_prompts_dir()
        if not prompts_dir.exists():
            return []
    except Exception:
        return []

    prompt_files = list(prompts_dir.glob("*.md"))
    if not prompt_files:
        return []

    prompt_names = {}
    for pf in prompt_files:
        prompt_names[pf.stem] = pf
        prompt_names[pf.stem.replace("-", "_")] = pf

    if not prompt_names:
        return []

    found_prompts = []

    for skill_group in skills_data:
        skill_path = Path(skill_group.get("path", ""))
        if not skill_path.exists():
            continue

        for file_info in skill_group.get("files", []):
            file_path = Path(file_info["path"])
            if not file_path.exists():
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            for prompt_key, pf in prompt_names.items():
                if prompt_key in content:
                    if not any(p["path"] == str(pf) for p in found_prompts):
                        found_prompts.append(
                            {
                                "name": pf.name,
                                "path": str(pf),
                                "relative": pf.name,
                            }
                        )

    return found_prompts


@router.post("/prompts-for-skills")
def prompts_for_skills(payload: SkillsData) -> list[dict]:
    """Filter prompts by detecting referenced prompts in skill files."""
    return _detect_prompts_in_skills(payload.skills)


@router.get("/file")
def get_file(path: str = Query(...)) -> dict[str, str]:
    file_path = Path(path).expanduser().resolve()
    roots_list = [p for p in _roots().values() if p is not None]

    from core.security import _assert_path_safe

    _assert_path_safe(file_path, roots_list)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    logger.info("skill_runner_read_file", path=str(file_path))
    return {
        "content": file_path.read_text(encoding="utf-8"),
        "language": _language_from_suffix(file_path),
    }


@router.put("/file")
def put_file(
    payload: FileUpdateRequest, path: str = Query(...)
) -> dict[str, str | bool]:
    file_path = Path(path).expanduser().resolve()
    roots_list = [p for p in _roots().values() if p is not None]

    from core.security import _assert_path_safe

    _assert_path_safe(file_path, roots_list)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    backup = file_path.with_name(f"{file_path.name}.bak")
    backup.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
    file_path.write_text(payload.content, encoding="utf-8")

    logger.info("skill_runner_save_file", path=str(file_path), backup=str(backup))
    return {"saved": True, "backup": str(backup)}


@router.post("/undo")
def undo_file(path: str = Query(...)) -> dict[str, bool]:
    file_path = Path(path).expanduser().resolve()
    roots_list = [p for p in _roots().values() if p is not None]

    from core.security import _assert_path_safe

    _assert_path_safe(file_path, roots_list)

    backup = file_path.with_name(f"{file_path.name}.bak")
    if not backup.exists() or not backup.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")

    file_path.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
    logger.info("skill_runner_undo_file", path=str(file_path), backup=str(backup))
    return {"restored": True}
