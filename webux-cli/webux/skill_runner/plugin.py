from __future__ import annotations

import json
import re
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
def list_plans() -> list[dict]:
    """List all YAML plan files in workdir_root."""
    roots_map = _roots()
    workdir = roots_map.get("workdir_root")
    if not workdir or not workdir.exists():
        return []

    plans = []
    for f in sorted(workdir.rglob("*.yaml"), key=lambda p: p.name.lower()):
        if f.is_file() and not f.is_symlink():
            plans.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "relative": str(f.relative_to(workdir)),
                }
            )
    for f in sorted(workdir.rglob("*.yml"), key=lambda p: p.name.lower()):
        if f.is_file() and not f.is_symlink():
            rel = str(f.relative_to(workdir))
            if not any(p["relative"] == rel for p in plans):
                plans.append(
                    {
                        "name": f.name,
                        "path": str(f),
                        "relative": rel,
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
            if f.is_file() and not f.is_symlink():
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


@router.post("/prompts-for-skills")
def prompts_for_skills(payload: SkillsData) -> list[dict]:
    """Filter prompts by grepping skill content for prompt: references."""
    skills_data = payload.skills

    prompt_names = set()
    skills_dir = get_skills_dir()

    for skill_group in skills_data:
        skill_path = Path(skill_group.get("path", ""))
        if not skill_path.exists():
            continue

        skill_file = skill_path / "SKILL.md"
        if skill_file.exists():
            content = skill_file.read_text(encoding="utf-8")
            for match in re.findall(r"prompt:\s*([^\s\n]+)", content):
                prompt_names.add(match.strip())

        run_sh = skill_path / "scripts" / "run.sh"
        if run_sh.exists():
            content = run_sh.read_text(encoding="utf-8")
            for match in re.findall(r"prompt:\s*([^\s\n]+)", content):
                prompt_names.add(match.strip())

    prompts_dir = get_prompts_dir()
    result = []

    for prompt_name in sorted(prompt_names):
        prompt_path = prompts_dir / f"{prompt_name}.md"
        if not prompt_path.exists():
            prompt_path = prompts_dir / f"{prompt_name}.yaml"
        if not prompt_path.exists():
            prompt_path = prompts_dir / f"{prompt_name}.yml"

        if prompt_path.exists():
            result.append(
                {
                    "name": prompt_path.name,
                    "path": str(prompt_path),
                    "relative": prompt_path.name,
                }
            )

    return result


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
