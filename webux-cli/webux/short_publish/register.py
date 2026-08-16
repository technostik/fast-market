from __future__ import annotations

import asyncio
import json
import tempfile
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
    redo_item,
    retry_item,
    get_pool_state,
    start_pool,
    stop_pool,
    skip_current,
    redo_unfinished,
    _load_pool_from_disk,
    clear_finished,
    rerun_check,
)

router = APIRouter()

_load_pool_from_disk()
_jobs: dict[str, Job] = {}

def _is_intermediate(path: Path) -> bool:
    return bool(_INTERMEDIATE_RE.search(path.stem))


from .pipeline import _run_pipeline_from, _run_post_publish_step, _run_transcript_script, _run_job_safely  # noqa: E402


def _create_publish_job(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False, transcript_mode: str = "normal", do_normalize_volume: bool = False, do_charisma: bool = True, do_add_signature: bool = True, do_ignore_post_publish: bool = False, title_override: str = "", cut_time: str = "") -> Job:
    """Create (but do not start) a publish Job. Used by pool worker.
    Respects publish config for default prompts etc.
    """
    pub = _load_publish_cfg()
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        title_override=title_override,
        prompt_title=pub.get("default_title_prompt", "youtube-title"),
        prompt_summary=pub.get("default_description_prompt", "youtube-summary"),
        prompt_check=pub.get("default_check_prompt", ""),
        do_remove_silence=True,
        do_burn_subtitles=True,
        transcript_mode=transcript_mode,
        language=pub.get("language", "fr"),
        model=pub.get("model", "medium"),
        privacy=pub.get("privacy", "unlisted"),
        description_prefix=description_prefix,
        source_urls=source_urls or [],
        skip_upload=skip_upload,
        do_normalize_volume=do_normalize_volume,
        do_charisma=do_charisma,
        do_add_signature=do_add_signature,
        do_ignore_post_publish=do_ignore_post_publish,
        cut_time=cut_time,
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    _jobs[job_id] = job
    return job


async def _run_single_publish_job(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False):
    """Legacy direct run (kept for compatibility)."""
    job = _create_publish_job(source, description_prefix, source_urls, skip_upload)
    await _run_job_safely(_run_pipeline_from(job, 0), job)


# ── Config API ────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    pub = _load_publish_cfg()
    return {
        "video_source_path": pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH),
        "video_extensions": pub.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS),
        "signature": pub.get("signature", ""),
        "signature_video_path": pub.get("signature_video_path", ""),
        "post_publish_script": pub.get("post_publish_script", ""),
        "transcript_script": pub.get("transcript_script", ""),
        "default_title_prompt": pub.get("default_title_prompt", "youtube-title"),
        "default_description_prompt": pub.get("default_description_prompt", "youtube-summary"),
        "default_check_prompt": pub.get("default_check_prompt", ""),
        "transcript_mode": pub.get("transcript_mode", "normal"),
        "modal_usage_url": pub.get("modal_usage_url", "https://modal.com/settings/usage"),
        "language": pub.get("language", "fr"),
        "model": pub.get("model", "medium"),
    }


class ConfigSaveRequest(BaseModel):
    video_source_path: str = DEFAULT_VIDEO_SOURCE_PATH
    video_extensions: str = DEFAULT_VIDEO_EXTENSIONS
    signature: str = ""
    signature_video_path: str = ""
    post_publish_script: str = ""
    transcript_script: str = ""
    default_title_prompt: str = "youtube-title"
    default_description_prompt: str = "youtube-summary"
    default_check_prompt: str = ""
    transcript_mode: str = "normal"
    modal_usage_url: str = "https://modal.com/settings/usage"
    language: str = ""
    model: str = ""


@router.post("/config")
async def save_config(req: ConfigSaveRequest):
    pub = _load_publish_cfg()
    pub["video_source_path"] = req.video_source_path
    pub["video_extensions"] = req.video_extensions
    pub["signature"] = req.signature
    pub["signature_video_path"] = req.signature_video_path
    pub["post_publish_script"] = req.post_publish_script
    pub["transcript_script"] = req.transcript_script
    pub["default_title_prompt"] = req.default_title_prompt
    pub["default_description_prompt"] = req.default_description_prompt
    pub["default_check_prompt"] = req.default_check_prompt
    pub["transcript_mode"] = req.transcript_mode
    pub["modal_usage_url"] = req.modal_usage_url
    pub["language"] = req.language
    pub["model"] = req.model
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

    # Collect all pipeline output file paths (no_silence, subtitled, final_video, etc.)
    # from existing meta files so we can exclude them from the source list.
    pipeline_outputs: set[str] = set()
    for meta_file in d.glob("*-meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            for val in meta.get("files", {}).values():
                if val:
                    resolved = str(Path(val).resolve())
                    pipeline_outputs.add(resolved)
        except Exception:
            pass

    files = sorted(
        [
            f for f in d.iterdir()
            if f.suffix.lower() in exts
            and not _is_intermediate(f)
            and str(f.resolve()) not in pipeline_outputs
        ],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # Build video list, hiding finished ones and tagging resumable ones
    visible = []
    for f in files:
        meta_path = f.with_name(f.stem + "-meta.json")
        resumable = False
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("status") == "finished":
                    continue
                completed = set(meta.get("completed_steps", []))
                skipped = set(meta.get("skipped_steps", []))
                passed = completed | skipped
                if set(range(len(STEP_NAMES))).issubset(passed):
                    continue  # all steps done via immediate publish (no pool "finished" marker)
                available = [c + 1 for c in passed if c + 1 < len(STEP_NAMES)]
                resumable = bool(available)
            except Exception:
                pass
        visible.append((f, resumable))

    return {
        "videos": [
            {"name": f.name, "path": str(f), "mtime": f.stat().st_mtime, "resumable": resumable}
            for f, resumable in visible
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


class QuickPromptRequest(BaseModel):
    prompt_name: str
    content: str


@router.post("/quick-prompt")
async def quick_prompt(req: QuickPromptRequest):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(req.content)
        tmp = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            _pr(), "apply", req.prompt_name, f"content=@{tmp}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode:
            err = stderr.decode(errors="replace").strip()
            return {"ok": False, "error": err or f"Exit code {proc.returncode}"}
        result = stdout.decode(errors="replace").strip()
        return {"ok": True, "result": result}
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass


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
    title: str = ""
    prompt_title: str
    prompt_summary: str
    prompt_check: str = ""
    do_remove_silence: bool = True
    do_burn_subtitles: bool = True
    transcript_mode: str = "normal"
    language: str = ""
    model: str = ""
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []
    skip_upload: bool = False
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_charisma: bool = True
    do_add_signature: bool = True
    ignore_post_publish: bool = False
    cut_time: str = ""


class ResumeRequest(BaseModel):
    source: str
    title: str = ""
    prompt_title: str
    prompt_summary: str
    prompt_check: str = ""
    from_step: int = 3
    do_burn_subtitles: bool = True
    transcript_mode: str = "normal"
    skip_upload: bool = False
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_charisma: bool = True
    do_add_signature: bool = True
    ignore_post_publish: bool = False
    language: str = ""
    model: str = ""
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []


@router.post("/start")
async def start(req: StartRequest):
    source = str(Path(req.source).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")

    pub = _load_publish_cfg()
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        title_override=req.title,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        prompt_check=req.prompt_check or pub.get("default_check_prompt", ""),
        do_remove_silence=req.do_remove_silence,
        do_burn_subtitles=req.do_burn_subtitles,
        transcript_mode=req.transcript_mode,
        language=req.language or pub.get("language", "fr"),
        model=req.model or pub.get("model", "medium"),
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        skip_upload=req.skip_upload,
        use_modal=req.use_modal,
        do_normalize_volume=req.do_normalize_volume,
        do_charisma=req.do_charisma,
        do_add_signature=req.do_add_signature,
        do_ignore_post_publish=req.ignore_post_publish,
        cut_time=req.cut_time,
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    _jobs[job_id] = job
    asyncio.create_task(_run_job_safely(_run_pipeline_from(job, 0), job))
    return {"job_id": job_id}


@router.get("/status/{job_id}")
async def status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        # Return a terminal response so browsers stop polling (avoids infinite 404 loop after restart)
        return {
            "status": "done", "gone": True, "job_id": job_id,
            "steps": [], "title": "", "description": "", "files": {},
            "video_url": "", "studio_url": "", "modal_url": "", "elapsed_seconds": None,
        }
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

    pub_cfg = _load_publish_cfg()
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        title_override=req.title,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        prompt_check=req.prompt_check or pub_cfg.get("default_check_prompt", ""),
        do_remove_silence=False,
        do_burn_subtitles=req.do_burn_subtitles,
        transcript_mode=req.transcript_mode,
        language=req.language or pub_cfg.get("language", "fr"),
        model=req.model or pub_cfg.get("model", "medium"),
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        skip_upload=req.skip_upload,
        use_modal=req.use_modal,
        do_normalize_volume=req.do_normalize_volume,
        do_charisma=req.do_charisma,
        do_add_signature=req.do_add_signature,
        do_ignore_post_publish=req.ignore_post_publish,
        steps=[Step(name=n) for n in STEP_NAMES],
        files=files,
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        transcript_text=meta.get("transcript_text", ""),
    )
    for i in completed_before:
        if i < from_step:
            job.steps[i].status = "done"
    for i in skipped_before:
        if i < from_step:
            job.steps[i].status = "skipped"

    _jobs[job_id] = job
    asyncio.create_task(_run_job_safely(_run_pipeline_from(job, from_step), job))
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
        "cut_time": meta.get("cut_time", ""),
    }


@router.post("/mark-step-done")
async def mark_step_done(body: dict):
    """Mark a specific step as done in the meta without re-running it."""
    source = str(Path(body.get("source", "")).expanduser().resolve())
    step = body.get("step")
    if step is None or not isinstance(step, int) or not (0 <= step < len(STEP_NAMES)):
        raise HTTPException(status_code=400, detail="Invalid step index")
    meta = _load_meta(source)
    completed = set(meta.get("completed_steps", []))
    skipped = set(meta.get("skipped_steps", []))
    completed.add(step)
    skipped.discard(step)
    meta["completed_steps"] = sorted(completed)
    meta["skipped_steps"] = sorted(skipped)
    try:
        p = Path(source).parent / f"{Path(source).stem}-meta.json"
        import json as _json
        p.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "completed_steps": meta["completed_steps"]}


@router.post("/redo-post-publish")
async def redo_post_publish(body: dict):
    source = str(Path(body.get("source", "")).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")

    meta = _load_meta(source)
    files = dict(meta.get("files", {}))
    final_video = files.get("final_video", source)
    if not Path(final_video).exists():
        raise HTTPException(status_code=400, detail=f"Final video not found: {final_video}")

    pub = _load_publish_cfg()
    completed_before = set(meta.get("completed_steps", []))
    skipped_before = set(meta.get("skipped_steps", []))

    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=pub.get("default_title_prompt", ""),
        prompt_summary=pub.get("default_description_prompt", ""),
        do_remove_silence=False,
        do_burn_subtitles=False,
        transcript_mode="normal",
        language=pub.get("language", "fr"),
        model=pub.get("model", "medium"),
        privacy=pub.get("privacy", "unlisted"),
        description_prefix=meta.get("description_prefix", ""),
        source_urls=meta.get("source_urls", []),
        skip_upload=True,
        steps=[Step(name=n) for n in STEP_NAMES],
        files=files,
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        transcript_text=meta.get("transcript_text", ""),
    )
    # Restore steps 0-4 from meta; step 5 starts fresh
    for i in range(5):
        if i in completed_before:
            job.steps[i].status = "done"
        elif i in skipped_before:
            job.steps[i].status = "skipped"
        else:
            job.steps[i].status = "skipped"

    _jobs[job_id] = job
    asyncio.create_task(_run_job_safely(_run_post_publish_step(job, final_video), job))
    return {"job_id": job_id}


@router.post("/review-info")
async def review_info(body: dict):
    source = str(Path(body.get("source", "")).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")
    meta = _load_meta(source)
    title = meta.get("title", "")
    description = meta.get("description", "")
    transcript_text = meta.get("transcript_text", "")
    files = meta.get("files", {})
    if not transcript_text:
        txt_path = files.get("transcript_txt", "")
        if txt_path and Path(txt_path).exists():
            transcript_text = Path(txt_path).read_text(encoding="utf-8")
        else:
            ass_path = files.get("transcript", "")
            if ass_path and Path(ass_path).exists():
                transcript_text = _ass_to_plain_text(ass_path)
    from .pool import find_pool_item
    pool_item = find_pool_item(source)
    video_url = meta.get("video_url", "") or (pool_item["video_url"] if pool_item else "")
    studio_url = meta.get("studio_url", "") or (pool_item["studio_url"] if pool_item else "")
    return {
        "title": title,
        "description": description,
        "transcript_text": transcript_text,
        "description_prefix": meta.get("description_prefix", ""),
        "source_urls": meta.get("source_urls", []),
        "video_url": video_url,
        "studio_url": studio_url,
        "source": source,
        "final_video": meta.get("files", {}).get("final_video", ""),
    }


@router.post("/run-transcript-script")
async def run_transcript_script(body: dict):
    source = str(Path(body.get("source", "")).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")
    meta = _load_meta(source)
    files = dict(meta.get("files", {}))
    transcript_path = files.get("transcript_txt", "")
    if not transcript_path or not Path(transcript_path).exists():
        ass_path = files.get("transcript", "")
        if ass_path and Path(ass_path).exists():
            stem = _stem(source)
            transcript_path = str(Path(source).parent / f"{stem}_transcript.txt")
            plain = _ass_to_plain_text(ass_path)
            Path(transcript_path).write_text(plain, encoding="utf-8")
            files["transcript_txt"] = transcript_path
        else:
            raise HTTPException(status_code=400, detail="Transcript not found")

    completed_before = set(meta.get("completed_steps", []))
    skipped_before = set(meta.get("skipped_steps", []))

    pub = _load_publish_cfg()
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=pub.get("default_title_prompt", ""),
        prompt_summary=pub.get("default_description_prompt", ""),
        do_remove_silence=False,
        do_burn_subtitles=False,
        transcript_mode="normal",
        language=pub.get("language", "fr"),
        model=pub.get("model", "medium"),
        privacy=pub.get("privacy", "unlisted"),
        description_prefix=meta.get("description_prefix", ""),
        source_urls=meta.get("source_urls", []),
        skip_upload=True,
        steps=[Step(name=n) for n in STEP_NAMES],
        files=files,
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        transcript_text=meta.get("transcript_text", ""),
    )
    for i in range(6):
        if i in completed_before:
            job.steps[i].status = "done"
        elif i in skipped_before:
            job.steps[i].status = "skipped"
        else:
            job.steps[i].status = "skipped"

    _jobs[job_id] = job
    asyncio.create_task(_run_job_safely(_run_transcript_script(job, transcript_path), job))
    return {"job_id": job_id}


# ── Pool API ──────────────────────────────────────────────────────────────────

@router.get("/pool")
async def pool_status():
    return get_pool_state()


class PoolAddRequest(BaseModel):
    source: str
    title: str = ""
    description_prefix: str = ""
    source_urls: list[str] = []
    skip_upload: bool = False
    transcript_mode: str = "normal"
    do_normalize_volume: bool = False
    do_charisma: bool = True
    do_add_signature: bool = True
    ignore_post_publish: bool = False
    cut_time: str = ""


@router.post("/pool/add")
async def pool_add(req: PoolAddRequest):
    ok = add_to_pool(req.source, req.description_prefix, req.source_urls, req.skip_upload, req.transcript_mode, req.do_normalize_volume, req.do_charisma, req.do_add_signature, req.ignore_post_publish, title_override=req.title, cut_time=req.cut_time)
    return {"ok": ok}


@router.post("/pool/remove")
async def pool_remove(body: dict):
    src = body.get("source", "")
    ok = remove_from_pool(src)
    return {"ok": ok}


@router.post("/pool/redo-item")
async def pool_redo_item(body: dict):
    src = body.get("source", "")
    ok = redo_item(src)
    return {"ok": ok}


@router.post("/pool/retry-item")
async def pool_retry_item(body: dict):
    src = body.get("source", "")
    ok = retry_item(src)
    return {"ok": ok}


@router.post("/pool/start")
async def pool_start():
    start_pool()
    return {"ok": True}


@router.post("/pool/stop")
async def pool_stop():
    stop_pool()
    from .state import request_stop
    request_stop()
    return {"ok": True}


@router.post("/pool/skip")
async def pool_skip():
    skip_current()
    return {"ok": True}


@router.post("/pool/redo")
async def pool_redo():
    redo_unfinished()
    return {"ok": True}


@router.post("/pool/clear-finished")
async def pool_clear_finished():
    clear_finished()
    return {"ok": True}


class RerunCheckRequest(BaseModel):
    source: str


@router.post("/pool/rerun-check")
async def pool_rerun_check(req: RerunCheckRequest):
    result = await rerun_check(req.source)
    if result is None:
        raise HTTPException(status_code=400, detail="Check failed or no transcript/prompt configured")
    return {"check_result": result}


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
        subprocess.run(["browser", "stop"], check=False, capture_output=True)
        r = subprocess.run(["browser", "start", "--hidden"], capture_output=True, text=True)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout).strip()}
        return {"ok": True, "log": r.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/browser/start-visible")
async def browser_start_visible():
    import subprocess
    try:
        subprocess.run(["browser", "stop"], check=False, capture_output=True)
        r = subprocess.run(["browser", "start"], capture_output=True, text=True)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout).strip()}
        return {"ok": True, "log": r.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/browser/screenshot")
async def browser_screenshot():
    import base64
    import subprocess
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="publish_screenshot_", delete=False)
    tmp.close()
    try:
        subprocess.run(["browser", "screenshot", "--output", tmp.name], check=True, capture_output=True)
        data = base64.b64encode(open(tmp.name, "rb").read()).decode()
        return {"ok": True, "image": f"data:image/png;base64,{data}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Frontend ──────────────────────────────────────────────────────────────────

def register(config: dict) -> WebuxPluginManifest:
    del config
    html = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")
    return WebuxPluginManifest(
        name="short_publish",
        tab_label="Short Publish",
        tab_icon="🚀",
        api_router=router,
        frontend_html=html,
        order=45,
        lazy=True,
    )
