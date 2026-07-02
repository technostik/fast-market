from __future__ import annotations

import asyncio
import json
import re
import shlex
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest

from .cache import get_cached_entry, load_cache, save_cache_entry, update_cache_scores
from .models import DEFAULT_EXTENSIONS, DEFAULT_FOLDER, FileResult, ScanJob, file_kind
from .utils import _sound, _video, default_extensions, default_folder, save_charisma_cfg

_VOLUME_LINE_RE = re.compile(r"(Input|Output) volume:\s*(-?\d+\.?\d*)\s*dB")

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


async def _measure_file(fr: FileResult, folder: Path) -> None:
    """Run `sound normalize-volume measure` and merge mean_volume_db into the folder's
    cache, on top of whatever scores (e.g. charisma) already exist for that file."""
    fr.status = "running"
    try:
        proc = await asyncio.create_subprocess_exec(
            _sound(), "normalize-volume", "measure", fr.path, "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            fr.status = "error"
            fr.error = (stderr.decode(errors="replace").strip() or f"exit code {proc.returncode}")[-500:]
            return
        result = json.loads(stdout.decode(errors="replace"))
        fr.scores = await update_cache_scores(folder, Path(fr.path), {"mean_volume_db": result["mean_volume_db"]})
        fr.status = "done"
        fr.cached = False
    except Exception as e:
        fr.status = "error"
        fr.error = str(e)


async def _run_volume_scan_job(job: ScanJob, to_measure: list[FileResult], folder: Path) -> None:
    """Measure only `to_measure` (files missing a cached mean_volume_db) with bounded concurrency."""
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _worker(fr: FileResult) -> None:
        async with sem:
            await _measure_file(fr, folder)

    await asyncio.gather(*(_worker(fr) for fr in to_measure))
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


class ReanalyzeRequest(BaseModel):
    file_path: str


# ── Reanalyze API ───────────────────────────────────────────────────────────────


@router.post("/reanalyze")
async def reanalyze(req: ReanalyzeRequest):
    p = Path(req.file_path).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")

    proc = await asyncio.create_subprocess_exec(
        _sound(), "charisma", str(p), "--format", "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {stderr.decode(errors='replace')[-500:]}",
        )

    scores = json.loads(stdout.decode(errors="replace"))
    await save_cache_entry(p.parent, p, scores)
    return scores


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


class NormalizeRequest(BaseModel):
    file_path: str


# ── Normalize volume API ───────────────────────────────────────────────────────


_NORMALIZABLE_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


async def _normalize_file(p: Path) -> dict:
    """Normalize p's audio volume in place against the configured reference, then
    re-measure its mean volume so the cache/table reflect the new value (not the
    stale pre-normalize dB). Returns {file_path, pre_db, post_db, scores}.
    Raises RuntimeError on failure (original file is left untouched)."""
    if p.suffix.lower() not in _NORMALIZABLE_EXTENSIONS:
        raise RuntimeError("Only video files are supported")

    backup = p.with_name(p.name + ".bak")
    shutil.copy2(str(p), str(backup))

    tmp = Path(tempfile.mkdtemp(prefix="charisma_norm_"))
    temp_output = tmp / "normalized.mp4"
    cmd = [_sound(), "normalize-volume", "apply", str(p), "--output", str(temp_output)]
    print(f"[charisma] Running: {shlex.join(cmd)}", flush=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_text, stderr_text = await proc.communicate()
        stdout_text = stdout_text.decode(errors="replace").strip()
        stderr_text = stderr_text.decode(errors="replace").strip()
        print(f"[charisma] normalize-volume exit={proc.returncode}", flush=True)
        if stdout_text:
            print(f"[charisma] stdout:\n{stdout_text}", flush=True)
        if stderr_text:
            print(f"[charisma] stderr:\n{stderr_text}", flush=True)

        if proc.returncode != 0 or not temp_output.exists():
            shutil.copy2(str(backup), str(p))
            backup.unlink(missing_ok=True)
            raise RuntimeError(f"Normalization failed (exit={proc.returncode}): {stderr_text[-2000:]}")

        # `apply`'s stdout reports the actual measured Input/Output volume (dB),
        # read back from the real files - not just derived from the makeup gain.
        volumes = {kind.lower(): float(db) for kind, db in _VOLUME_LINE_RE.findall(stdout_text)}
        pre_db = volumes.get("input")
        post_db = volumes.get("output")

        # Replace original with normalized version
        original_size = p.stat().st_size
        shutil.copy2(str(temp_output), str(p))
        new_size = p.stat().st_size
        backup.unlink(missing_ok=True)
        print(f"[charisma] normalize-volume done: {p} ({original_size} → {new_size} bytes)", flush=True)

        # Re-measure (rather than trust the makeup-gain math) and merge into the
        # cache on top of whatever's already there (e.g. charisma scores),
        # without clobbering them.
        scores = None
        if post_db is not None:
            scores = await update_cache_scores(p.parent, p, {"mean_volume_db": post_db})

        return {"file_path": str(p), "pre_db": pre_db, "post_db": post_db, "scores": scores}
    except RuntimeError:
        raise
    except Exception as e:
        shutil.copy2(str(backup), str(p))
        backup.unlink(missing_ok=True)
        raise RuntimeError(str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.post("/normalize")
async def normalize(req: NormalizeRequest):
    p = Path(req.file_path).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        result = await _normalize_file(p)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, **result}


class NormalizeAllRequest(BaseModel):
    folder: str
    extensions: str = DEFAULT_EXTENSIONS


async def _normalize_worker(fr: FileResult) -> None:
    fr.status = "running"
    try:
        result = await _normalize_file(Path(fr.path))
        fr.scores = result.get("scores") or {"mean_volume_db": result.get("post_db")}
        fr.status = "done"
        fr.cached = False
    except RuntimeError as e:
        fr.status = "error"
        fr.error = str(e)[:500]
    except Exception as e:
        fr.status = "error"
        fr.error = str(e)[:500]


async def _run_normalize_all_job(job: ScanJob, to_normalize: list[FileResult]) -> None:
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _worker(fr: FileResult) -> None:
        async with sem:
            await _normalize_worker(fr)

    await asyncio.gather(*(_worker(fr) for fr in to_normalize))
    job.status = "done"
    job.end_time = time.time()


@router.post("/normalize_all")
async def normalize_all(req: NormalizeAllRequest):
    """Same job/polling model as /start and /volume_scan, but normalizes every
    video file in the folder against the configured reference volume, one
    ffmpeg pass + charisma reanalysis per file, bounded concurrency."""
    files = [f for f in _scan_folder(req.folder, req.extensions) if f.suffix.lower() in _NORMALIZABLE_EXTENSIONS]
    folder_path = Path(req.folder).expanduser()

    file_results = [FileResult(path=str(f), name=f.name, kind=file_kind(f.suffix)) for f in files]

    job_id = str(uuid.uuid4())
    job = ScanJob(job_id=job_id, folder=str(folder_path), files=file_results)
    _jobs[job_id] = job

    if not file_results:
        job.status = "done"
        job.end_time = time.time()
    else:
        asyncio.create_task(_run_normalize_all_job(job, file_results))

    return {"job_id": job_id, "total": len(file_results)}


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


class VolumeScanRequest(BaseModel):
    folder: str
    extensions: str = DEFAULT_EXTENSIONS
    force_recompute: bool = False


@router.post("/volume_scan")
async def volume_scan(req: VolumeScanRequest):
    """Same job/polling model as /start, but measures mean volume (dBFS) per file
    instead of running charisma analysis. Reuses the same .charisma-scores.json
    cache entries (merging mean_volume_db alongside any existing charisma scores)
    and the same /status/{job_id} polling endpoint."""
    files = _scan_folder(req.folder, req.extensions)
    folder_path = Path(req.folder).expanduser()

    cache = {"files": {}} if req.force_recompute else load_cache(folder_path)
    file_results: list[FileResult] = []
    to_measure: list[FileResult] = []
    for f in files:
        fr = FileResult(path=str(f), name=f.name, kind=file_kind(f.suffix))
        cached_entry = get_cached_entry(cache, f)
        if cached_entry:
            fr.scores = cached_entry["scores"]
        if cached_entry and not req.force_recompute and "mean_volume_db" in cached_entry["scores"]:
            fr.cached = True
            fr.status = "done"
        else:
            to_measure.append(fr)
        file_results.append(fr)

    job_id = str(uuid.uuid4())
    job = ScanJob(job_id=job_id, folder=str(folder_path), files=file_results)
    _jobs[job_id] = job

    if not to_measure:
        job.status = "done"
        job.end_time = time.time()
    else:
        asyncio.create_task(_run_volume_scan_job(job, to_measure, folder_path))

    return {"job_id": job_id, "total": len(files), "cached": len(files) - len(to_measure)}


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
    # The file can be overwritten in place (e.g. by /normalize), always at the
    # same path/URL - without this, browsers may keep serving stale cached
    # bytes for a video that has since changed on disk.
    return FileResponse(
        str(p), media_type=mime,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


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
