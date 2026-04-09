from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from common import structlog
from common.core.config import load_common_config
from core.security import _assert_path_safe

logger = structlog.get_logger(__name__)
router = APIRouter()


class PostRequest(BaseModel):
    file: str
    indices: list[int]
    dry_run: bool = False


def _workdir() -> Path:
    workdir = load_common_config().get("workdir")
    if not workdir:
        raise HTTPException(status_code=404, detail="workdir is not configured")
    return Path(workdir).expanduser().resolve()


def _resolve_workdir_relative(relative_path: str) -> Path:
    workdir = _workdir()
    candidate = (workdir / relative_path).expanduser().resolve()
    _assert_path_safe(candidate, [workdir])
    return candidate


def _load_array(path: Path) -> list:
    raw = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}") from exc

    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail="Expected top-level array")
    return data


@router.get("/load")
def load(file: str = Query(...)) -> list:
    path = _resolve_workdir_relative(file)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    logger.info("yt_poster_load", file=file, path=str(path))
    return _load_array(path)


@router.post("/post")
def post(payload: PostRequest) -> dict[str, int | str | bool]:
    source_path = _resolve_workdir_relative(payload.file)
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="Input file not found")

    data = _load_array(source_path)
    selected = [item for idx, item in enumerate(data) if idx in set(payload.indices)]

    temp_path = Path(tempfile.gettempdir()) / f"webux_post_{uuid4().hex}.json"
    temp_path.write_text(json.dumps(selected, ensure_ascii=False), encoding="utf-8")

    cmd = ["youtube", "batch-post", str(temp_path), "--format", "json"]
    if payload.dry_run:
        cmd.append("--dry-run")

    logger.info(
        "yt_poster_exec",
        cmd=" ".join(cmd),
        selected_count=len(selected),
        dry_run=payload.dry_run,
    )

    report_path = source_path.parent / f"{source_path.stem}.batch-post-report.json"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = (proc.stdout or "") + (proc.stderr or "")

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_file": str(source_path),
            "dry_run": payload.dry_run,
            "selected_count": len(selected),
            "exit_code": proc.returncode,
            "output": output,
            "items": selected,
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "exit_code": proc.returncode,
            "output": output,
            "dry_run": payload.dry_run,
            "report": str(report_path),
        }
    finally:
        temp_path.unlink(missing_ok=True)
