from __future__ import annotations

import asyncio
import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.core.config import load_common_config, load_tool_config
from core.security import _assert_path_safe

router = APIRouter()

_SPAWN_TIMEOUT_S = 900  # L2 subprocess failsafe per fast-market ADR 009

_ENGINE_LINE_RE = re.compile(r"--engine\s*\[([^\]]+)\]")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_MIME = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def _sound() -> str:
    return shutil.which("sound") or "sound"


def _workdir() -> Path:
    workdir = load_common_config().get("workdir")
    if not workdir:
        raise HTTPException(
            status_code=400,
            detail="workdir not set in common config — run: toolsetup workdir init <path>",
        )
    return Path(workdir).expanduser()


# Running generation jobs (for busy_check; single POST at a time keeps
# VRAM exclusive — two TTS models loading simultaneously would OOM an 8 GB card).
_jobs: set[str] = set()

# Debug ring buffer: one entry per generation attempt with its CLI output.
_LOGS: list[dict] = []
_LOGS_MAX = 50
_LOG_ENTRY_MAX_CHARS = 40000


def _clip_log(log: str) -> str:
    return log[-_LOG_ENTRY_MAX_CHARS:] if len(log) > _LOG_ENTRY_MAX_CHARS else log


def _record_log(entry: dict, ok: bool, log: str) -> None:
    entry.update(ok=ok, log=_clip_log(log), done_ts=time.time())
    _LOGS.insert(0, entry)
    del _LOGS[_LOGS_MAX:]


def _is_busy() -> bool:
    return bool(_jobs)


class GenerateRequest(BaseModel):
    engine: str
    text: str
    voice: str = ""
    language: str | None = None
    speed: float | None = None
    exaggeration: float | None = None
    accelerate: float | None = None
    clone: str | None = None


# ── Introspection API ────────────────────────────────────────────────────────


@router.get("/engines")
async def engines():
    """Available TTS engines (parsed from `sound speak --help`) + profile config."""
    try:
        proc = await asyncio.create_subprocess_exec(
            _sound(), "speak", "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=(stderr.decode(errors="replace") or f"exit {proc.returncode}")[-500:],
            )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="sound speak --help timed out")
    match = _ENGINE_LINE_RE.search(_ANSI_RE.sub("", stdout.decode(errors="replace")))
    if not match:
        raise HTTPException(status_code=500, detail="Could not parse engine choices from 'sound speak --help'")
    names = [e for e in match.group(1).split("|") if e]

    cfg: dict = {}
    try:
        cfg = load_tool_config("sound")
    except Exception:
        pass  # unfiled profile config: the CLI holds its own defaults
    return {"engines": names, "config": cfg}


# ── Generation API ───────────────────────────────────────────────────────────


@router.post("/generate")
async def generate(req: GenerateRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    if len(_jobs) >= 1:
        raise HTTPException(status_code=409, detail="A generation is already running")

    out_dir = _workdir() / "soundlab"
    out_path = out_dir / f"tts_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    out_dir.mkdir(parents=True, exist_ok=True)

    argv = [_sound(), "speak", req.text, "--engine", req.engine, "--format", "json", "--output", str(out_path)]
    if req.voice.strip():
        argv += ["--voice", req.voice.strip()]
    if req.language:
        argv += ["--language", req.language]
    if req.speed is not None:
        argv += ["--speed", str(req.speed)]
    if req.exaggeration is not None:
        argv += ["--exaggeration", str(req.exaggeration)]
    if req.accelerate is not None:
        argv += ["--accelerate", str(req.accelerate)]
    if req.clone:
        clone = Path(req.clone).expanduser()
        if not clone.is_file():
            raise HTTPException(status_code=400, detail=f"clone file not found: {clone}")
        argv += ["--clone", str(clone.resolve())]

    job_id = f"gen_{time.time()}"
    _jobs.add(job_id)
    entry = {
        "id": job_id,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "engine": req.engine,
        "text": req.text[:120],
        "output": str(out_path),
        "ok": False,
        "done_ts": None,
        "log": "",
    }
    p: asyncio.subprocess.Process | None = None
    stdout = b""
    stderr = b""
    try:
        p = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(p.communicate(), timeout=_SPAWN_TIMEOUT_S)
        except asyncio.TimeoutError:
            p.kill()
            await p.wait()
            log = f"sound speak killed after {_SPAWN_TIMEOUT_S}s — engine too slow or hung"
            _record_log(entry, ok=False, log=log)
            raise HTTPException(status_code=504, detail=log)
        combined = (
            "── stderr ──────────────────────────────\n"
            + stderr.decode(errors="replace")
            + ("\n── stdout ──────────────────────────────\n" if stdout else "")
            + stdout.decode(errors="replace")
        ).strip()
        if p.returncode != 0:
            _record_log(entry, ok=False, log=combined)
            raise HTTPException(
                status_code=500,
                detail=(stderr.decode(errors="replace").strip() or f"sound speak exited {p.returncode}")[-1000:],
            )
        if not out_path.exists():
            _record_log(entry, ok=False, log=combined)
            raise HTTPException(
                status_code=500,
                detail=(stderr.decode(errors="replace").strip() or "no output file was produced")[-500:],
            )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="sound CLI not found in PATH")
    finally:
        _jobs.discard(job_id)

    _record_log(entry, ok=True, log=combined)
    return {
        "output": str(out_path),
        "engine": req.engine,
        "text": req.text,
        "ts": out_path.stat().st_mtime,
        "job_id": job_id,
        "log": entry["log"],
    }


# ── Debug log API ────────────────────────────────────────────────────────────


@router.get("/logs")
async def logs():
    """Recent generation attempts with their full `sound speak` output."""
    return {"entries": _LOGS}


@router.delete("/logs")
async def clear_logs():
    _LOGS.clear()
    return {"ok": True}


# ── Audio preview API ────────────────────────────────────────────────────────


@router.get("/preview")
async def preview(path: str = Query(...)):
    p = Path(path).expanduser().resolve()
    _assert_path_safe(p, [_workdir()])
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    mime = _MIME.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=mime, headers={"Cache-Control": "no-store"})
