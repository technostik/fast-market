from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest

from .models import (
    Job,
    Step,
    STEP_NAMES,
    DEFAULT_VIDEO_SOURCE_PATH,
    DEFAULT_VIDEO_EXTENSIONS,
    _INTERMEDIATE_RE,
    _STEP_FILE_KEYS,
)
from .utils import (
    _load_publish_cfg,
    _save_publish_cfg,
    _load_meta,
    _pr,
    _stem,
    _ass_to_plain_text,
    _validate_urls,
)
from .pool import (
    add_to_pool,
    remove_from_pool,
    get_pool_state,
    start_pool,
    stop_pool,
    skip_current,
    redo_current,
    _load_pool_from_disk,
    clear_finished,
)

router = APIRouter()

_jobs: dict[str, Job] = {}

_load_pool_from_disk()


def _is_intermediate(path: Path) -> bool:
    return bool(_INTERMEDIATE_RE.search(path.stem))


from .pipeline import _run_pipeline_from  # noqa: E402


def _create_publish_job(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False) -> Job:
    """Create (but do not start) a publish Job. Used by pool worker.
    Respects publish config for default prompts etc.
    """
    pub = _load_publish_cfg()
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=pub.get("default_title_prompt", "youtube-title"),
        prompt_summary=pub.get("default_description_prompt", "youtube-summary"),
        do_remove_silence=True,
        do_burn_subtitles=True,
        simple_transcript=True,
        language=pub.get("language", "fr"),
        model=pub.get("model", "medium"),
        privacy=pub.get("privacy", "unlisted"),
        description_prefix=description_prefix,
        source_urls=source_urls or [],
        skip_upload=skip_upload,
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    _jobs[job_id] = job
    return job


async def _run_single_publish_job(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False):
    """Legacy direct run (kept for compatibility)."""
    job = _create_publish_job(source, description_prefix, source_urls, skip_upload)
    await _run_pipeline_from(job, 0)


# ── Config API ────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    pub = _load_publish_cfg()
    return {
        "video_source_path": pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH),
        "video_extensions": pub.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS),
        "signature": pub.get("signature", ""),
        "post_publish_script": pub.get("post_publish_script", ""),
        "default_title_prompt": pub.get("default_title_prompt", "youtube-title"),
        "default_description_prompt": pub.get("default_description_prompt", "youtube-summary"),
    }


class ConfigSaveRequest(BaseModel):
    video_source_path: str = DEFAULT_VIDEO_SOURCE_PATH
    video_extensions: str = DEFAULT_VIDEO_EXTENSIONS
    signature: str = ""
    post_publish_script: str = ""
    default_title_prompt: str = "youtube-title"
    default_description_prompt: str = "youtube-summary"


@router.post("/config")
async def save_config(req: ConfigSaveRequest):
    pub = _load_publish_cfg()
    pub["video_source_path"] = req.video_source_path
    pub["video_extensions"] = req.video_extensions
    pub["signature"] = req.signature
    pub["post_publish_script"] = req.post_publish_script
    pub["default_title_prompt"] = req.default_title_prompt
    pub["default_description_prompt"] = req.default_description_prompt
    _save_publish_cfg(pub)
    return {"ok": True}


# ── Video list API ────────────────────────────────────────────────────────────

@router.get("/list-videos")
async def list_videos(
    path: str = Query(default=DEFAULT_VIDEO_SOURCE_PATH),
    extensions: str = Query(default=DEFAULT_VIDEO_EXTENSIONS),
):
    d = Path(path).expanduser()
    if not d.exists() or not d.is_dir():
        return {"videos": [], "error": f"Directory not found: {path}"}
    exts = {("." + e.strip().lstrip(".")).lower() for e in extensions.split(",") if e.strip()}
    files = sorted(
        [f for f in d.iterdir() if f.suffix.lower() in exts and not _is_intermediate(f)],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # Hide videos that have finished meta
    visible = []
    for f in files:
        meta_path = f.with_name(f.stem + "-meta.json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("status") == "finished":
                    continue
            except Exception:
                pass
        visible.append(f)

    return {
        "videos": [
            {"name": f.name, "path": str(f), "mtime": f.stat().st_mtime}
            for f in visible
        ]
    }


# ── Prompt list API ───────────────────────────────────────────────────────────

@router.get("/list-prompts")
async def list_prompts():
    pr = _pr()
    proc = await asyncio.create_subprocess_exec(
        pr, "list", "--names-only",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    names = [n.strip() for n in stdout.decode(errors="replace").splitlines() if n.strip()]
    return {"prompts": names}


# ── Video preview API ─────────────────────────────────────────────────────────

_MIME = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}

@router.get("/video-preview")
async def video_preview(file: str = Query(...)):
    p = Path(file).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    mime = _MIME.get(p.suffix.lower(), "video/mp4")
    return FileResponse(str(p), media_type=mime)


@router.get("/download")
async def download_file(file: str = Query(...)):
    p = Path(file).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(p), filename=p.name)


@router.post("/upload-external")
async def upload_external(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".mkv", ".mov", ".webm"}:
        raise HTTPException(status_code=400, detail="Unsupported video format")
    pub_cfg = _load_publish_cfg()
    source_dir = Path(pub_cfg.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)).expanduser()
    source_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(file.filename).stem
    dest = source_dir / f"{stem}{ext}"
    if dest.exists():
        dest = source_dir / f"{stem}_{uuid.uuid4().hex[:8]}{ext}"
    with open(dest, "wb") as f:
        f.write(await file.read())
    return {"path": str(dest), "name": file.filename}


# ── Job API ───────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    source: str
    prompt_title: str
    prompt_summary: str
    do_remove_silence: bool = True
    do_burn_subtitles: bool = True
    simple_transcript: bool = True
    language: str = "fr"
    model: str = "medium"
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []
    skip_upload: bool = False


class ResumeRequest(BaseModel):
    source: str
    prompt_title: str
    prompt_summary: str
    from_step: int = 3
    do_burn_subtitles: bool = True
    simple_transcript: bool = True
    skip_upload: bool = False
    language: str = "fr"
    model: str = "medium"
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []


@router.post("/start")
async def start(req: StartRequest):
    source = str(Path(req.source).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")

    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        do_remove_silence=req.do_remove_silence,
        do_burn_subtitles=req.do_burn_subtitles,
        simple_transcript=req.simple_transcript,
        language=req.language,
        model=req.model,
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        skip_upload=req.skip_upload,
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    _jobs[job_id] = job
    asyncio.create_task(_run_pipeline_from(job, 0))
    return {"job_id": job_id}


@router.get("/status/{job_id}")
async def status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.post("/resume")
async def resume(req: ResumeRequest):
    source = str(Path(req.source).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")

    meta = _load_meta(source)
    files = dict(meta.get("files", {}))

    from_step = max(1, min(req.from_step, len(STEP_NAMES) - 1))

    # Validate required artifacts exist for the requested entry point
    if from_step >= 2:
        ass = files.get("transcript", "")
        if not ass or not Path(ass).exists():
            raise HTTPException(status_code=400, detail="Transcript (.ass) not found; cannot resume from step 2+")
    if from_step >= 3:
        txt = files.get("transcript_txt", "")
        if not txt or not Path(txt).exists():
            ass = files.get("transcript", "")
            if ass and Path(ass).exists():
                stem = _stem(source)
                txt_path = str(Path(source).parent / f"{stem}_transcript.txt")
                plain = _ass_to_plain_text(ass)
                with open(txt_path, "w", encoding="utf-8") as _f:
                    _f.write(plain)
                files["transcript_txt"] = txt_path
            else:
                raise HTTPException(status_code=400, detail="Transcript text not found; cannot resume from step 3+")

    completed_before = set(meta.get("completed_steps", []))
    skipped_before = set(meta.get("skipped_steps", []))

    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        do_remove_silence=False,
        do_burn_subtitles=req.do_burn_subtitles,
        simple_transcript=req.simple_transcript,
        language=req.language,
        model=req.model,
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        skip_upload=req.skip_upload,
        steps=[Step(name=n) for n in STEP_NAMES],
        files=files,
        title=meta.get("title", ""),
        description=meta.get("description", ""),
    )
    for i in completed_before:
        if i < from_step:
            job.steps[i].status = "done"
    for i in skipped_before:
        if i < from_step:
            job.steps[i].status = "skipped"

    _jobs[job_id] = job
    asyncio.create_task(_run_pipeline_from(job, from_step))
    return {"job_id": job_id}


@router.post("/check-resume")
async def check_resume(body: dict):
    source = str(Path(body.get("source", "")).expanduser().resolve())
    meta = _load_meta(source)
    completed = set(meta.get("completed_steps", []))
    skipped = set(meta.get("skipped_steps", []))
    passed = completed | skipped
    available = sorted({c + 1 for c in passed if c + 1 < len(STEP_NAMES)})
    files = meta.get("files", {})
    step_files = [
        [
            {"path": files[k], "name": Path(files[k]).name}
            for k in keys
            if k in files and files[k] and Path(files[k]).exists()
        ]
        for keys in _STEP_FILE_KEYS
    ]
    return {
        "can_resume": bool(available),
        "available_from_steps": available,
        "completed_steps": sorted(completed),
        "skipped_steps": sorted(skipped),
        "step_files": step_files,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "source_urls": meta.get("source_urls", []),
        "description_prefix": meta.get("description_prefix", ""),
    }


# ── Pool API ──────────────────────────────────────────────────────────────────

@router.get("/pool")
async def pool_status():
    return get_pool_state()


class PoolAddRequest(BaseModel):
    source: str
    description_prefix: str = ""
    source_urls: list[str] = []
    skip_upload: bool = False


@router.post("/pool/add")
async def pool_add(req: PoolAddRequest):
    ok = add_to_pool(req.source, req.description_prefix, req.source_urls, req.skip_upload)
    return {"ok": ok}


@router.post("/pool/remove")
async def pool_remove(body: dict):
    src = body.get("source", "")
    ok = remove_from_pool(src)
    return {"ok": ok}


@router.post("/pool/start")
async def pool_start():
    start_pool()
    return {"ok": True}


@router.post("/pool/stop")
async def pool_stop():
    stop_pool()
    return {"ok": True}


@router.post("/pool/skip")
async def pool_skip():
    skip_current()
    return {"ok": True}


@router.post("/pool/redo")
async def pool_redo():
    redo_current()
    return {"ok": True}


@router.post("/pool/clear-finished")
async def pool_clear_finished():
    clear_finished()
    return {"ok": True}


# ── Browser visibility control ────────────────────────────────────────────────

@router.post("/browser/hide")
async def browser_hide():
    import subprocess
    try:
        subprocess.run(["browser", "hide"], check=True, capture_output=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/browser/show")
async def browser_show():
    import subprocess
    try:
        subprocess.run(["browser", "show"], check=True, capture_output=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/browser/start-silent")
async def browser_start_silent():
    import subprocess
    try:
        subprocess.run(["browser", "start", "-s"], check=True, capture_output=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Frontend ──────────────────────────────────────────────────────────────────

def register(config: dict) -> WebuxPluginManifest:
    del config
    html = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")
    return WebuxPluginManifest(
        name="publish",
        tab_label="Publish",
        tab_icon="🚀",
        api_router=router,
        frontend_html=html,
        order=45,
        lazy=True,
    )
