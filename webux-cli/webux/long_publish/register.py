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
from .pipeline import _run_pipeline_from, _run_job_safely  # noqa: E402

router = APIRouter()

_jobs: dict[str, Job] = {}


def _is_intermediate(path: Path) -> bool:
    return bool(_INTERMEDIATE_RE.search(path.stem))


def _create_publish_job(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False, transcript_mode: str = "normal", do_normalize_volume: bool = False, do_add_signature: bool = True, do_generate_thumbnail: bool = True, thumbnail_overlay_title: str = "", use_modal: bool = True, do_remove_silence: bool = True, language: str = "fr", model: str = "medium", privacy: str = "unlisted") -> Job:
    """Create (but do not start) a publish Job. Respects publish config for
    default prompts etc."""
    pub = _load_publish_cfg()
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=pub.get("default_title_prompt", "youtube-title"),
        prompt_summary=pub.get("default_description_prompt", "youtube-summary"),
        do_remove_silence=do_remove_silence,
        transcript_mode=transcript_mode,
        language=language,
        model=model,
        privacy=privacy,
        description_prefix=description_prefix,
        source_urls=source_urls or [],
        skip_upload=skip_upload,
        use_modal=use_modal,
        do_normalize_volume=do_normalize_volume,
        do_add_signature=do_add_signature,
        do_generate_thumbnail=do_generate_thumbnail,
        thumbnail_overlay_title=thumbnail_overlay_title,
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    _jobs[job_id] = job
    return job


# ── Config API ────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    pub = _load_publish_cfg()
    return {
        "video_source_path": pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH),
        "video_extensions": pub.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS),
        "signature": pub.get("signature", ""),
        "signature_video_path": pub.get("signature_video_path", ""),
        "default_title_prompt": pub.get("default_title_prompt", "youtube-title"),
        "default_description_prompt": pub.get("default_description_prompt", "youtube-summary"),
        "default_thumbnail_prompt": pub.get("default_thumbnail_prompt", ""),
        "default_thumbnail_overlay_prompt": pub.get("default_thumbnail_overlay_prompt", ""),
        "thumbnail_engine": pub.get("thumbnail_engine", ""),
        "thumbnail_overlay_fg": pub.get("thumbnail_overlay_fg", ""),
        "thumbnail_overlay_bg": pub.get("thumbnail_overlay_bg", ""),
        "transcript_mode": pub.get("transcript_mode", "normal"),
        "transcript_model": pub.get("transcript_model", "medium"),
        "transcript_language": pub.get("transcript_language", "fr"),
        "modal_usage_url": pub.get("modal_usage_url", "https://modal.com/settings/usage"),
    }


class ConfigSaveRequest(BaseModel):
    video_source_path: str = DEFAULT_VIDEO_SOURCE_PATH
    video_extensions: str = DEFAULT_VIDEO_EXTENSIONS
    signature: str = ""
    signature_video_path: str = ""
    default_title_prompt: str = "youtube-title"
    default_description_prompt: str = "youtube-summary"
    default_thumbnail_prompt: str = ""
    default_thumbnail_overlay_prompt: str = ""
    thumbnail_engine: str = ""
    thumbnail_overlay_fg: str = ""
    thumbnail_overlay_bg: str = ""
    transcript_mode: str = "normal"
    transcript_model: str = "medium"
    transcript_language: str = "fr"
    modal_usage_url: str = "https://modal.com/settings/usage"


@router.post("/config")
async def save_config(req: ConfigSaveRequest):
    pub = _load_publish_cfg()
    pub["video_source_path"] = req.video_source_path
    pub["video_extensions"] = req.video_extensions
    pub["signature"] = req.signature
    pub["signature_video_path"] = req.signature_video_path
    pub["default_title_prompt"] = req.default_title_prompt
    pub["default_description_prompt"] = req.default_description_prompt
    pub["default_thumbnail_prompt"] = req.default_thumbnail_prompt
    pub["default_thumbnail_overlay_prompt"] = req.default_thumbnail_overlay_prompt
    pub["thumbnail_engine"] = req.thumbnail_engine
    pub["thumbnail_overlay_fg"] = req.thumbnail_overlay_fg
    pub["thumbnail_overlay_bg"] = req.thumbnail_overlay_bg
    pub["transcript_mode"] = req.transcript_mode
    pub["transcript_model"] = req.transcript_model
    pub["transcript_language"] = req.transcript_language
    pub["modal_usage_url"] = req.modal_usage_url
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

    pipeline_outputs: set[str] = set()
    for meta_file in d.glob("*-long-meta.json"):
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

    visible = []
    for f in files:
        meta_path = f.with_name(f.stem + "-long-meta.json")
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
                    continue
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
    prompt_title: str
    prompt_summary: str
    do_remove_silence: bool = True
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []
    skip_upload: bool = False
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_add_signature: bool = True
    do_generate_thumbnail: bool = True
    thumbnail_overlay_title: str = ""


class ResumeRequest(BaseModel):
    source: str
    prompt_title: str
    prompt_summary: str
    from_step: int = 3
    skip_upload: bool = False
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_add_signature: bool = True
    do_generate_thumbnail: bool = True
    do_remove_silence: bool = False
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []
    thumbnail_overlay_title: str = ""


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
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        do_remove_silence=req.do_remove_silence,
        transcript_mode=pub.get("transcript_mode", "normal"),
        language=pub.get("transcript_language", "fr"),
        model=pub.get("transcript_model", "medium"),
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        skip_upload=req.skip_upload,
        use_modal=req.use_modal,
        do_normalize_volume=req.do_normalize_volume,
        do_add_signature=req.do_add_signature,
        do_generate_thumbnail=req.do_generate_thumbnail,
        thumbnail_overlay_title=req.thumbnail_overlay_title,
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    _jobs[job_id] = job
    asyncio.create_task(_run_job_safely(_run_pipeline_from(job, 0), job))
    return {"job_id": job_id}


@router.get("/status/{job_id}")
async def status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
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
                raise HTTPException(status_code=400, detail="Transcript text not found; cannot resume from step 2+")
    if from_step >= 3:
        if not meta.get("title"):
            raise HTTPException(status_code=400, detail="Title not found in saved state; cannot resume from thumbnail step")
    if from_step >= 4:
        fv = files.get("final_video", "")
        if not fv or not Path(fv).exists():
            raise HTTPException(status_code=400, detail="Final video not found; cannot resume from step 4+")
    if from_step >= 5:
        if not (files.get("final_video") and Path(files.get("final_video", "")).exists()):
            raise HTTPException(status_code=400, detail="Final video not found; cannot resume from upload")
        if not meta.get("title") or not meta.get("description"):
            raise HTTPException(status_code=400, detail="Title/description not found; cannot resume from upload")

    completed_before = set(meta.get("completed_steps", []))
    skipped_before = set(meta.get("skipped_steps", []))

    pub = _load_publish_cfg()
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        do_remove_silence=req.do_remove_silence,
        transcript_mode=pub.get("transcript_mode", "normal"),
        language=pub.get("transcript_language", "fr"),
        model=pub.get("transcript_model", "medium"),
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        skip_upload=req.skip_upload,
        use_modal=req.use_modal,
        do_normalize_volume=req.do_normalize_volume,
        do_add_signature=req.do_add_signature,
        do_generate_thumbnail=req.do_generate_thumbnail if not req.do_generate_thumbnail else meta.get("do_generate_thumbnail", True),
        thumbnail_overlay_title=req.thumbnail_overlay_title or meta.get("thumbnail_overlay_title", ""),
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
        "thumbnail_overlay_title": meta.get("thumbnail_overlay_title", ""),
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
        p = Path(source).parent / f"{Path(source).stem}-long-meta.json"
        p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "completed_steps": meta["completed_steps"]}


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
    return {
        "title": title,
        "description": description,
        "transcript_text": transcript_text,
        "description_prefix": meta.get("description_prefix", ""),
        "source_urls": meta.get("source_urls", []),
        "thumbnail_overlay_title": meta.get("thumbnail_overlay_title", ""),
        "video_url": meta.get("video_url", ""),
        "studio_url": meta.get("studio_url", ""),
        "source": source,
        "final_video": meta.get("files", {}).get("final_video", ""),
        "thumbnail": meta.get("files", {}).get("thumbnail", ""),
    }


# ── Thumbnail regeneration API ────────────────────────────────────────────────

@router.get("/list-thumbnails")
async def list_thumbnails(
    path: str = Query(default=DEFAULT_VIDEO_SOURCE_PATH),
    extensions: str = Query(default=DEFAULT_VIDEO_EXTENSIONS),
):
    """List every source video (including already-published ones) along with its
    existing thumbnail info, so the overlay can be regenerated."""
    d = Path(path).expanduser()
    if not d.exists() or not d.is_dir():
        return {"videos": [], "error": f"Directory not found: {path}"}
    exts = {("." + e.strip().lstrip(".")).lower() for e in extensions.split(",") if e.strip()}
    files = sorted(
        [
            f for f in d.iterdir()
            if f.suffix.lower() in exts and not _is_intermediate(f)
        ],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    visible = []
    for f in files:
        meta_path = f.with_name(f.stem + "-long-meta.json")
        thumb = ""
        thumb_base = ""
        video_url = ""
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                thumb = meta.get("files", {}).get("thumbnail", "")
                thumb_base = meta.get("files", {}).get("thumbnail_base", "")
                video_url = meta.get("video_url", "")
            except Exception:
                pass
        visible.append({
            "name": f.name,
            "path": str(f),
            "mtime": f.stat().st_mtime,
            "thumbnail": thumb,
            "thumbnail_base": thumb_base,
            "video_url": video_url,
            "has_thumbnail": bool(thumb and Path(thumb).exists()),
        })
    return {"videos": visible}


class RegenThumbRequest(BaseModel):
    source: str
    overlay_title: str
    overlay_fg: str = ""
    overlay_bg: str = ""
    overlay_effect: str = ""


@router.post("/regenerate-thumbnail")
async def regenerate_thumbnail(req: RegenThumbRequest):
    """Regenerate only the overlay text on an existing thumbnail image (the
    no-overlay base when available, otherwise a full regeneration using the
    stored image prompt). Does NOT touch YouTube."""
    source = str(Path(req.source).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")
    if not req.overlay_title.strip():
        raise HTTPException(status_code=400, detail="Overlay title is required")

    meta = _load_meta(source)
    files = dict(meta.get("files", {}))

    base = files.get("thumbnail_base", "")
    if not base or not Path(base).expanduser().exists():
        base = files.get("thumbnail", "")
    base_is_clean = bool(base) and Path(base).expanduser().exists()

    if base_is_clean and Path(base).expanduser().stem.endswith("_overlay") is False:
        # We have a clean (no-overlay) base image: just reapply the overlay.
        cmd = [_image(), "overlay", str(Path(base).expanduser().resolve()), "--title", req.overlay_title.strip(), "-F", "json"]
        if req.overlay_fg.strip():
            cmd += ["--overlay-fg", req.overlay_fg.strip()]
        if req.overlay_bg.strip():
            cmd += ["--overlay-bg", req.overlay_bg.strip()]
        if req.overlay_effect.strip():
            cmd += ["--overlay-effect", req.overlay_effect.strip()]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode:
            err = stderr.decode(errors="replace").strip()
            raise HTTPException(status_code=500, detail=err or f"Exit code {proc.returncode}")
        new_path = ""
        try:
            text = stdout.decode(errors="replace")
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(text[start:end])
                new_path = data.get("path", "")
        except (json.JSONDecodeError, ValueError, TypeError):
            new_path = ""
        if not new_path or not Path(new_path).expanduser().exists():
            raise HTTPException(status_code=500, detail="Overlay output path not found in command output")
        new_path = str(Path(new_path).expanduser().resolve())
        files["thumbnail"] = new_path
    else:
        # No clean base available (e.g. a video published before base images
        # were stored). Regenerate from scratch using the stored image prompt,
        # if we have one.
        image_prompt = meta.get("thumbnail_prompt", "").strip()
        if not image_prompt:
            raise HTTPException(
                status_code=400,
                detail="No clean base image or stored prompt for this video; "
                       "re-run publish to regenerate the thumbnail from scratch",
            )
        out_dir = str(Path(source).parent)
        cmd = [_image(), "generate", image_prompt, "--size", "youtube", "-F", "json", "--output-dir", out_dir, "--title", req.overlay_title.strip()]
        if req.overlay_fg.strip():
            cmd += ["--overlay-fg", req.overlay_fg.strip()]
        if req.overlay_bg.strip():
            cmd += ["--overlay-bg", req.overlay_bg.strip()]
        if req.overlay_effect.strip():
            cmd += ["--overlay-effect", req.overlay_effect.strip()]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode:
            err = stderr.decode(errors="replace").strip()
            raise HTTPException(status_code=500, detail=err or f"Exit code {proc.returncode}")
        new_path = ""
        new_base = ""
        try:
            text = stdout.decode(errors="replace")
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(text[start:end])
                new_path = data.get("path", "")
                new_base = data.get("base_path", "")
        except (json.JSONDecodeError, ValueError, TypeError):
            new_path = ""
            new_base = ""
        if not new_path or not Path(new_path).expanduser().exists():
            raise HTTPException(status_code=500, detail="Thumbnail output path not found in command output")
        new_path = str(Path(new_path).expanduser().resolve())
        files["thumbnail"] = new_path
        if new_base and Path(new_base).expanduser().exists():
            files["thumbnail_base"] = str(Path(new_base).expanduser().resolve())

    meta["files"] = files
    meta["thumbnail_overlay_title"] = req.overlay_title.strip()
    try:
        p = Path(source).parent / f"{Path(source).stem}-long-meta.json"
        p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"thumbnail": new_path, "base": files.get("thumbnail_base", "")}


class PushThumbRequest(BaseModel):
    source: str
    thumbnail: str = ""


@router.post("/push-thumbnail")
async def push_thumbnail(req: PushThumbRequest):
    """Explicit action: push the (already regenerated) thumbnail to YouTube for
    the published video associated with this source."""
    source = str(Path(req.source).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")

    meta = _load_meta(source)
    thumb = req.thumbnail or meta.get("files", {}).get("thumbnail", "")
    video_url = meta.get("video_url", "")
    video_id = _extract_video_id(video_url)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="No YouTube video ID found for this source; cannot push thumbnail",
        )
    if not thumb or not Path(thumb).expanduser().exists():
        raise HTTPException(status_code=400, detail="No thumbnail available to push")

    thumb = str(Path(thumb).expanduser().resolve())
    cmd = [_yt(), "thumbnail-set", video_id, "--file", thumb]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        err = stderr.decode(errors="replace").strip()
        raise HTTPException(status_code=500, detail=err or f"Exit code {proc.returncode}")

    return {"ok": True, "video_id": video_id}


# ── Frontend ──────────────────────────────────────────────────────────────────

def register(config: dict) -> WebuxPluginManifest:
    del config
    html = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")
    return WebuxPluginManifest(
        name="long_publish",
        tab_label="Long Publish",
        tab_icon="🎬",
        api_router=router,
        frontend_html=html,
        order=46,
        lazy=True,
    )
