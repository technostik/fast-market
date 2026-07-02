from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest

from .cache import get_cached_entry, load_cache, save_cache_entry
from .models import DEFAULT_EXTENSIONS, DEFAULT_FOLDER, FileResult, ScanJob, file_kind
from .utils import _sound, _video, default_extensions, default_folder, save_charisma_cfg

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


async def _analyze_file(fr: FileResult, folder: Path) -> None:
    """Run a fresh `sound charisma` analysis and persist it to the folder's cache.
    Only called for files that were NOT resolved from cache in `start()`."""
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
        fr.cached = False
        await save_cache_entry(folder, Path(fr.path), fr.scores)
    except Exception as e:
        fr.status = "error"
        fr.error = str(e)


async def _run_scan_job(job: ScanJob, to_analyze: list[FileResult], folder: Path) -> None:
    """Analyze only `to_analyze` (files that missed the cache) with bounded concurrency.
    Cache hits are already resolved synchronously in start() and never enter this queue."""
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _worker(fr: FileResult) -> None:
        async with sem:
            await _analyze_file(fr, folder)

    await asyncio.gather(*(_worker(fr) for fr in to_analyze))
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
    folder_path = Path(path).expanduser()
    cache = load_cache(folder_path)
    results = []
    for f in files:
        clone_path = folder_path / f"{f.stem}.mp3"
        results.append({
            "name": f.name,
            "path": str(f),
            "kind": file_kind(f.suffix),
            "cached": get_cached_entry(cache, f) is not None,
            "has_clone": clone_path.exists(),
        })
    return {"files": results}


class StartRequest(BaseModel):
    folder: str
    extensions: str = DEFAULT_EXTENSIONS
    force_recompute: bool = False


class CloneRequest(BaseModel):
    file_path: str
    text: str


# ── Clone API ──────────────────────────────────────────────────────────────────


@router.post("/clone")
async def clone(req: CloneRequest):
    p = Path(req.file_path).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    output_path = p.parent / f"{p.stem}.mp3"

    tmp = Path(tempfile.mkdtemp(prefix="charisma_clone_"))
    try:
        transcript_path = tmp / "transcript.txt"

        # 1. Transcribe the video to get reference text for voice cloning
        proc = await asyncio.create_subprocess_exec(
            _video(), "extract-transcript", req.file_path,
            "--format", "txt", "--output", str(transcript_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Transcription failed: {stderr.decode(errors='replace')[-1000:]}",
            )

        if not transcript_path.exists():
            raise HTTPException(status_code=500, detail="Transcription produced no output file")

        transcript = transcript_path.read_text(encoding="utf-8").strip()
        if not transcript:
            raise HTTPException(status_code=500, detail="Transcription is empty")

        # 2. Generate TTS with voice cloning using the video's audio + transcript
        proc = await asyncio.create_subprocess_exec(
            _sound(), "speak", req.text,
            "--engine", "qwen3",
            "--clone", req.file_path,
            "--ref-text", transcript,
            "--format", "json",
            "--output", str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not output_path.exists():
            raise HTTPException(
                status_code=500,
                detail=f"TTS cloning failed: {stderr.decode(errors='replace')[-1000:]}",
            )

        return {"output_path": str(output_path), "transcript": transcript}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.post("/start")
async def start(req: StartRequest):
    files = _scan_folder(req.folder, req.extensions)
    save_charisma_cfg(req.folder, req.extensions)
    folder_path = Path(req.folder).expanduser()

    # Resolve cache hits synchronously and up front, so they never touch the
    # analysis queue — only files missing from (or invalidated in) the folder's
    # .charisma-scores.json get queued for a fresh `sound charisma` run.
    cache = {"files": {}} if req.force_recompute else load_cache(folder_path)
    file_results: list[FileResult] = []
    to_analyze: list[FileResult] = []
    for f in files:
        fr = FileResult(path=str(f), name=f.name, kind=file_kind(f.suffix))
        cached_entry = get_cached_entry(cache, f)
        if cached_entry:
            fr.scores = cached_entry["scores"]
            fr.cached = True
            fr.status = "done"
        else:
            to_analyze.append(fr)
        file_results.append(fr)

    job_id = str(uuid.uuid4())
    job = ScanJob(job_id=job_id, folder=str(folder_path), files=file_results)
    _jobs[job_id] = job

    if not to_analyze:
        job.status = "done"
        job.end_time = time.time()
    else:
        asyncio.create_task(_run_scan_job(job, to_analyze, folder_path))

    return {"job_id": job_id, "total": len(files), "cached": len(files) - len(to_analyze)}


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
