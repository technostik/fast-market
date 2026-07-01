from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest

from .models import DEFAULT_EXTENSIONS, DEFAULT_FOLDER, FileResult, ScanJob, file_kind
from .utils import _sound, default_extensions, default_folder, save_charisma_cfg

router = APIRouter()

_jobs: dict[str, ScanJob] = {}

_CONCURRENCY = 3

_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".m4v": "video/mp4",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def _parse_extensions(extensions: str) -> set[str]:
    return {("." + e.strip().lstrip(".")).lower() for e in extensions.split(",") if e.strip()}


def _scan_folder(folder: str, extensions: str) -> list[Path]:
    d = Path(folder).expanduser()
    if not d.exists() or not d.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {folder}")
    exts = _parse_extensions(extensions)
    return sorted(
        (f for f in d.iterdir() if f.is_file() and f.suffix.lower() in exts),
        key=lambda f: f.name.lower(),
    )


async def _analyze_file(fr: FileResult) -> None:
    fr.status = "running"
    try:
        proc = await asyncio.create_subprocess_exec(
            _sound(), "charisma", fr.path, "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            fr.status = "error"
            fr.error = (stderr.decode(errors="replace").strip() or f"exit code {proc.returncode}")[-500:]
            return
        fr.scores = json.loads(stdout.decode(errors="replace"))
        fr.status = "done"
    except Exception as e:
        fr.status = "error"
        fr.error = str(e)


async def _run_scan_job(job: ScanJob) -> None:
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _worker(fr: FileResult) -> None:
        async with sem:
            await _analyze_file(fr)

    await asyncio.gather(*(_worker(fr) for fr in job.files))
    job.status = "done"
    job.end_time = time.time()


# ── Config API ────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    return {"folder": default_folder(), "extensions": default_extensions()}


# ── Scan API ──────────────────────────────────────────────────────────────────

@router.get("/scan")
async def scan(
    path: str = Query(default=DEFAULT_FOLDER),
    extensions: str = Query(default=DEFAULT_EXTENSIONS),
):
    files = _scan_folder(path, extensions)
    save_charisma_cfg(path, extensions)
    return {
        "files": [
            {"name": f.name, "path": str(f), "kind": file_kind(f.suffix)}
            for f in files
        ]
    }


class StartRequest(BaseModel):
    folder: str
    extensions: str = DEFAULT_EXTENSIONS


@router.post("/start")
async def start(req: StartRequest):
    files = _scan_folder(req.folder, req.extensions)
    save_charisma_cfg(req.folder, req.extensions)

    job_id = str(uuid.uuid4())
    job = ScanJob(
        job_id=job_id,
        folder=req.folder,
        files=[FileResult(path=str(f), name=f.name, kind=file_kind(f.suffix)) for f in files],
    )
    _jobs[job_id] = job

    if not files:
        job.status = "done"
        job.end_time = time.time()
    else:
        asyncio.create_task(_run_scan_job(job))

    return {"job_id": job_id, "total": len(files)}


@router.get("/status/{job_id}")
async def status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


# ── Media preview API ─────────────────────────────────────────────────────────

@router.get("/preview")
async def preview(file: str = Query(...)):
    p = Path(file).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    mime = _MIME.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=mime)


def register(config: dict) -> WebuxPluginManifest:
    del config
    html = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")
    return WebuxPluginManifest(
        name="charisma",
        tab_label="Charisma",
        tab_icon="🎤",
        api_router=router,
        frontend_html=html,
        order=70,
        lazy=True,
    )
