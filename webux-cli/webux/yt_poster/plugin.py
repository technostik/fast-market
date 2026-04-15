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


class SaveReplyRequest(BaseModel):
    file: str
    index: int
    reply: str


class RegenerateRequest(BaseModel):
    file: str
    indices: list[int]


class GetPromptRequest(BaseModel):
    name: str


class SavePromptRequest(BaseModel):
    name: str
    content: str


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
        raise HTTPException(
            status_code=422, detail=f"Failed to parse file: {exc}"
        ) from exc

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


@router.post("/save_reply")
def save_reply(payload: SaveReplyRequest) -> dict[str, str]:
    source_path = _resolve_workdir_relative(payload.file)
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="Input file not found")

    data = _load_array(source_path)
    if payload.index < 0 or payload.index >= len(data):
        raise HTTPException(status_code=404, detail="Index out of range")

    # Update the reply field in the data
    item = data[payload.index]
    item["reply"] = payload.reply
    item["generated_reply"] = payload.reply

    # Write back to the source file
    source_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(
        "yt_poster_save_reply",
        file=payload.file,
        index=payload.index,
        reply_length=len(payload.reply),
    )

    return {"status": "ok"}


@router.post("/get_prompt")
def get_prompt(payload: GetPromptRequest) -> dict[str, str]:
    cmd = ["prompt", "get", payload.name, "--content"]
    logger.info("yt_poster_get_prompt", prompt_name=payload.name)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {"status": "ok", "content": proc.stdout}
    except subprocess.CalledProcessError as exc:
        logger.error("yt_poster_get_prompt_failed", error=exc.stderr)
        raise HTTPException(status_code=500, detail=exc.stderr.strip())


@router.post("/save_prompt")
def save_prompt(payload: SavePromptRequest) -> dict[str, str]:
    cmd = ["prompt", "edit", payload.name, "--content"]
    logger.info("yt_poster_save_prompt", prompt_name=payload.name)
    try:
        proc = subprocess.run(
            cmd,
            input=payload.content,
            capture_output=True,
            text=True,
            check=True,
        )
        return {"status": "ok"}
    except subprocess.CalledProcessError as exc:
        logger.error("yt_poster_save_prompt_failed", error=exc.stderr)
        raise HTTPException(status_code=500, detail=exc.stderr.strip())


@router.post("/regenerate")
def regenerate(payload: RegenerateRequest) -> dict[str, int | str]:
    source_path = _resolve_workdir_relative(payload.file)
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="Input file not found")

    data = _load_array(source_path)
    selected = [data[idx] for idx in payload.indices if 0 <= idx < len(data)]

    if not selected:
        raise HTTPException(status_code=400, detail="No valid rows selected")

    prompt_name = selected[0].get("metadata", {}).get("prompt-name")
    promote_url = selected[0].get("metadata", {}).get("promote-url")

    if not prompt_name:
        raise HTTPException(status_code=400, detail="No prompt-name in metadata")

    comment_ids = [
        item.get("original_comment", {}).get("id")
        for item in selected
        if item.get("original_comment", {}).get("id")
    ]

    temp_input = Path(tempfile.gettempdir()) / f"webux_regen_{uuid4().hex}.json"
    temp_output = Path(tempfile.gettempdir()) / f"webux_regen_out_{uuid4().hex}.json"
    temp_input.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    cmd = [
        "youtube",
        "batch-reply",
        str(temp_input),
        "-s",
        f"prompt apply {prompt_name}",
        "-o",
        str(temp_output),
        "--filter",
        json.dumps(comment_ids),
        "--rewrite",
    ]

    if promote_url:
        cmd.extend(["-p", f"URL={promote_url}"])

    logger.info(
        "yt_poster_regenerate",
        cmd=" ".join(cmd),
        indices=payload.indices,
        prompt_name=prompt_name,
    )

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode != 0:
            return {
                "exit_code": proc.returncode,
                "output": output,
                "error": f"batch-reply failed: {output}",
            }

        if temp_output.exists():
            updated_data = json.loads(temp_output.read_text(encoding="utf-8"))
            source_path.write_text(
                json.dumps(updated_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "exit_code": 0,
                "output": output,
                "updated_count": len(comment_ids),
            }

        return {"exit_code": proc.returncode, "output": output}
    finally:
        temp_input.unlink(missing_ok=True)
        temp_output.unlink(missing_ok=True)
