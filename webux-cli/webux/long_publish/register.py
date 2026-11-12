from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common import structlog
from common.core.paths import get_profiles_config_base
from common.core.profile import resolve_profile
from common.webux.base import WebuxPluginManifest
from common.webux.transcripts import find_transcript

logger = structlog.get_logger(__name__)

from .models import (
    Job,
    Step,
    STEP_NAMES,
    RHYTHM_STEP_NAMES,
    MAX_TITLE_LEN,
    rhythm_params_from_pub,
    DEFAULT_VIDEO_SOURCE_PATH,
    DEFAULT_VIDEO_EXTENSIONS,
    _INTERMEDIATE_RE,
    _STEP_FILE_KEYS,
)
from .utils import (
    _load_publish_cfg,
    _save_publish_cfg,
    _migrate_publish_cfg_if_needed,
    video_extension_set,
    _load_meta,
    _long_meta_path,
    _pr,
    _image,
    _validate_urls,
)
from .pipeline import _run_pipeline_from, _run_job_safely, _compose_description  # noqa: E402

router = APIRouter()

_jobs: dict[str, Job] = {}


def _is_intermediate(path: Path) -> bool:
    return bool(_INTERMEDIATE_RE.search(path.stem))


def _is_busy() -> bool:
    """True while a publish job is active (feeds GET /api/system/busy)."""
    return any(
        job.status not in ("done", "error", "stopped")
        for job in list(_jobs.values())
    )


def _validate_rhythm_options(rhythm_silence: bool, use_modal: bool, transcript_mode: str, do_remove_silence: bool) -> None:
    """Reject rhythm-mode combinations the pipeline cannot run (HTTP 400)."""
    if not rhythm_silence:
        return
    if use_modal:
        raise HTTPException(
            status_code=400,
            detail="Rhythm silence mode is local-only (word-level JSON + transcript-aware cut); uncheck 'Use Modal' to use it.",
        )
    if transcript_mode == "none":
        raise HTTPException(
            status_code=400,
            detail="Rhythm silence mode needs a transcript; pick a transcript mode first.",
        )
    if not do_remove_silence:
        raise HTTPException(
            status_code=400,
            detail="Rhythm silence mode requires 'Remove silence' to be enabled.",
        )


def _validate_manual_title(title_override: str, rhythm_silence: bool) -> str:
    """Validate a forced title; returns it stripped (``""`` = AI-generated).

    A forced title disables the Whisper pass, so rhythm mode (which cuts with
    the word-level transcript) cannot run with it.
    """
    title = (title_override or "").strip()
    if not title:
        return ""
    if len(title) > MAX_TITLE_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Manual title is {len(title)} chars; YouTube allows {MAX_TITLE_LEN}. Shorten it before running.",
        )
    if rhythm_silence:
        raise HTTPException(
            status_code=400,
            detail="A manual title disables rhythm silence mode (it needs the word-level transcript). Pick 'Remove silence' or clear the title.",
        )
    return title


def _create_publish_job(source: str, description_prefix: str = "", source_urls: list[str] | None = None, skip_upload: bool = False, transcript_mode: str = "normal", do_normalize_volume: bool = False, do_add_signature: bool = True, do_generate_thumbnail: bool = True, thumbnail_overlay_title: str = "", thumbnail_overlay_subtitle: str = "", use_modal: bool = True, do_remove_silence: bool = True, rhythm_silence: bool = False, language: str = "fr", model: str = "medium", privacy: str = "unlisted", do_pinned_comment: bool | None = None, pinned_comment_text: str | None = None, title_override: str = "", description_override: str = "", profile: str | None = None, do_add_to_corpus: bool = True) -> Job:
    """Create (but do not start) a publish Job. Respects publish config for
    default prompts etc."""
    if not profile:
        profile = resolve_profile()
    pub = _load_publish_cfg(profile)
    job_id = str(uuid.uuid4())
    step_names = RHYTHM_STEP_NAMES if rhythm_silence else STEP_NAMES
    job = Job(
        job_id=job_id,
        source=source,
        profile=profile,
        prompt_title=pub.get("default_title_prompt", "youtube-title"),
        prompt_summary=pub.get("default_description_prompt", "youtube-summary"),
        do_remove_silence=do_remove_silence,
        rhythm_silence=rhythm_silence,
        transcript_mode=transcript_mode,
        language=language,
        model=model,
        privacy=privacy,
        description_prefix=description_prefix,
        source_urls=source_urls or [],
        title_override=title_override,
        description_override=description_override,
        skip_upload=skip_upload,
        use_modal=use_modal,
        do_normalize_volume=do_normalize_volume,
        do_add_signature=do_add_signature,
        do_generate_thumbnail=do_generate_thumbnail,
        do_pinned_comment=do_pinned_comment if do_pinned_comment is not None else bool(pub.get("long_pinned_comment_enabled", False)),
        pinned_comment_text=pinned_comment_text if pinned_comment_text is not None else str(pub.get("long_pinned_comment_text", "") or ""),
        do_add_to_corpus=do_add_to_corpus,
        thumbnail_overlay_title=thumbnail_overlay_title,
        thumbnail_overlay_subtitle=thumbnail_overlay_subtitle,
        steps=[Step(name=n) for n in step_names],
    )
    _jobs[job_id] = job
    return job


# ── Profiles API ──────────────────────────────────────────────────────────────

@router.get("/profiles")
async def list_profiles():
    base = get_profiles_config_base()
    names = []
    if base.exists():
        for p in sorted(base.iterdir()):
            if p.is_dir():
                names.append(p.name)
    return {"profiles": names, "active": resolve_profile()}


# ── Config API ────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config(profile: str | None = Query(default=None)):
    if not profile:
        profile = resolve_profile()
    from .utils import _profile_context
    with _profile_context(profile):
        _migrate_publish_cfg_if_needed()
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
        "thumbnail_overlay_effect": pub.get("thumbnail_overlay_effect", ""),
        "thumbnail_overlay_band_size": pub.get("thumbnail_overlay_band_size", 0),
        "thumbnail_overlay_size_pct": pub.get("thumbnail_overlay_size_pct", 0),
        "thumbnail_overlay_offset": pub.get("thumbnail_overlay_offset", 0),
        "transcript_mode": pub.get("transcript_mode", "normal"),
        "transcript_model": pub.get("transcript_model", "medium"),
        "transcript_language": pub.get("transcript_language", "fr"),
        "long_pinned_comment_enabled": pub.get("long_pinned_comment_enabled", False),
        "long_pinned_comment_text": pub.get("long_pinned_comment_text", ""),
        "default_category": pub.get("default_category", ""),
        "rhythm_transcript_tolerance": pub.get("rhythm_transcript_tolerance"),
        "rhythm_paragraph_threshold": pub.get("rhythm_paragraph_threshold"),
        "rhythm_pause_inline": pub.get("rhythm_pause_inline"),
        "rhythm_pause_comma": pub.get("rhythm_pause_comma"),
        "rhythm_pause_sentence": pub.get("rhythm_pause_sentence"),
        "rhythm_pause_paragraph": pub.get("rhythm_pause_paragraph"),
        "rhythm_crossfade": pub.get("rhythm_crossfade"),
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
    thumbnail_overlay_effect: str = ""
    thumbnail_overlay_band_size: int = 0
    thumbnail_overlay_size_pct: float = 0
    thumbnail_overlay_offset: int = 0
    transcript_mode: str = "normal"
    transcript_model: str = "medium"
    transcript_language: str = "fr"
    long_pinned_comment_enabled: bool = False
    long_pinned_comment_text: str = ""
    default_category: str = ""
    rhythm_transcript_tolerance: float | None = None
    rhythm_paragraph_threshold: float | None = None
    rhythm_pause_inline: float | None = None
    rhythm_pause_comma: float | None = None
    rhythm_pause_sentence: float | None = None
    rhythm_pause_paragraph: float | None = None
    rhythm_crossfade: float | None = None
    modal_usage_url: str = "https://modal.com/settings/usage"


def _rhythm_config_from_request(req: ConfigSaveRequest) -> dict:
    """Collect rhythm tuning fields for validation/storage (None = unset)."""
    return {
        "rhythm_transcript_tolerance": req.rhythm_transcript_tolerance,
        "rhythm_paragraph_threshold": req.rhythm_paragraph_threshold,
        "rhythm_pause_inline": req.rhythm_pause_inline,
        "rhythm_pause_comma": req.rhythm_pause_comma,
        "rhythm_pause_sentence": req.rhythm_pause_sentence,
        "rhythm_pause_paragraph": req.rhythm_pause_paragraph,
        "rhythm_crossfade": req.rhythm_crossfade,
    }


@router.post("/config")
async def save_config(req: ConfigSaveRequest, profile: str | None = Query(default=None)):
    if not profile:
        profile = resolve_profile()
    from .utils import _profile_context
    with _profile_context(profile):
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
        pub["thumbnail_overlay_effect"] = req.thumbnail_overlay_effect
        pub["thumbnail_overlay_band_size"] = req.thumbnail_overlay_band_size
        pub["thumbnail_overlay_size_pct"] = req.thumbnail_overlay_size_pct
        pub["thumbnail_overlay_offset"] = req.thumbnail_overlay_offset
        pub["transcript_mode"] = req.transcript_mode
        pub["transcript_model"] = req.transcript_model
        pub["transcript_language"] = req.transcript_language
        pub["long_pinned_comment_enabled"] = req.long_pinned_comment_enabled
        pub["long_pinned_comment_text"] = req.long_pinned_comment_text
        pub["default_category"] = req.default_category
        rhythm_cfg = _rhythm_config_from_request(req)
        try:
            rhythm_params_from_pub(rhythm_cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for key, value in rhythm_cfg.items():
            if value is None:
                pub.pop(key, None)  # cleared field = unset, keep the file tidy
            else:
                pub[key] = value
        pub["modal_usage_url"] = req.modal_usage_url
        _save_publish_cfg(pub)
    return {"ok": True}


# ── Image engines API ────────────────────────────────────────────────────────

@router.get("/list-engines")
async def list_engines():
    """List available image generation engines from the image CLI."""
    try:
        proc = await asyncio.create_subprocess_exec(
            _image(), "setup", "engine", "list", "-f", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode:
            return {"engines": [], "default": ""}
        data = json.loads(stdout.decode(errors="replace"))
        return {
            "engines": data.get("engines", []),
            "default": data.get("default", ""),
        }
    except Exception:
        return {"engines": [], "default": ""}


# ── Video list API ────────────────────────────────────────────────────────────

@router.get("/list-videos")
async def list_videos(
    path: str = Query(default=DEFAULT_VIDEO_SOURCE_PATH),
    extensions: str = Query(default=DEFAULT_VIDEO_EXTENSIONS),
):
    d = Path(path).expanduser()
    if not d.exists() or not d.is_dir():
        return {"videos": [], "error": f"Directory not found: {path}"}
    exts = video_extension_set(extensions)

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
                # Hidden only when fully processed AND uploaded: a run whose
                # tail steps were skipped (no thumbnail/signature/upload) never
                # published anything, so the source stays selectable.
                if set(range(len(STEP_NAMES))).issubset(passed) and len(STEP_NAMES) - 1 in completed:
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
async def list_prompts(profile: str | None = Query(default=None)):
    pr = _pr()
    # Scope the prompt CLI to the requested profile without mutating the
    # process-wide FASTMARKET_PROFILE (a running job may own it).
    env = dict(os.environ)
    if profile:
        env["FASTMARKET_PROFILE"] = profile
    proc = await asyncio.create_subprocess_exec(
        pr, "list", "--names-only",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, _ = await proc.communicate()
    names = [n.strip() for n in stdout.decode(errors="replace").splitlines() if n.strip()]
    return {"prompts": names}


class QuickPromptRequest(BaseModel):
    prompt_name: str
    content: str
    profile: str | None = None


@router.post("/quick-prompt")
async def quick_prompt(req: QuickPromptRequest):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(req.content)
        tmp = f.name
    try:
        from .utils import _job_env
        class _JobProxy:
            profile = req.profile or resolve_profile()
        proc = await asyncio.create_subprocess_exec(
            _pr(), "apply", req.prompt_name, f"content=@{tmp}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_job_env(_JobProxy()),
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
    rhythm_silence: bool = False
    cut_time: str = ""
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []
    skip_upload: bool = False
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_add_signature: bool = True
    do_generate_thumbnail: bool = True
    do_pinned_comment: bool | None = None
    pinned_comment_text: str | None = None
    do_add_to_corpus: bool = True
    thumbnail_overlay_title: str = ""
    thumbnail_overlay_subtitle: str = ""
    thumbnail_engine: str = ""
    title_override: str = ""
    description_override: str = ""
    profile: str = ""


class ResumeRequest(BaseModel):
    source: str
    prompt_title: str
    prompt_summary: str
    from_step: int = 3
    skip_upload: bool = False
    profile: str = ""
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_add_signature: bool = True
    do_generate_thumbnail: bool = True
    do_pinned_comment: bool | None = None
    pinned_comment_text: str | None = None
    # None = follow the meta log (retry of a run that already chose).
    do_add_to_corpus: bool | None = None
    do_remove_silence: bool = False
    rhythm_silence: bool = False
    cut_time: str = ""
    privacy: str = "unlisted"
    description_prefix: str = ""
    source_urls: list[str] = []
    thumbnail_overlay_title: str = ""
    thumbnail_overlay_subtitle: str = ""
    thumbnail_engine: str = ""
    # None = caller omitted the field (fall back to the meta log);
    # "" = explicitly cleared (back to AI generation).
    title_override: str | None = None
    description_override: str | None = None


def _job_rhythm_params(pub: dict) -> dict[str, float]:
    """Validated rhythm overrides from the publish config (HTTP 400 if bad)."""
    try:
        return rhythm_params_from_pub(pub)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/start")
async def start(req: StartRequest):
    source = str(Path(req.source).expanduser().resolve())
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")

    profile = req.profile or resolve_profile()
    pub = _load_publish_cfg(profile)
    transcript_mode = pub.get("transcript_mode", "normal")
    _validate_rhythm_options(req.rhythm_silence, req.use_modal, transcript_mode, req.do_remove_silence)
    title_override = _validate_manual_title(req.title_override, req.rhythm_silence)
    description_override = (req.description_override or "").strip()
    job_id = str(uuid.uuid4())
    step_names = RHYTHM_STEP_NAMES if req.rhythm_silence else STEP_NAMES
    job = Job(
        job_id=job_id,
        source=source,
        profile=profile,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        do_remove_silence=req.do_remove_silence,
        rhythm_silence=req.rhythm_silence,
        rhythm_params=_job_rhythm_params(pub),
        cut_time=req.cut_time.strip(),
        transcript_mode=transcript_mode,
        language=pub.get("transcript_language", "fr"),
        model=pub.get("transcript_model", "medium"),
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        title_override=title_override,
        description_override=description_override,
        skip_upload=req.skip_upload,
        use_modal=req.use_modal,
        do_normalize_volume=req.do_normalize_volume,
        do_add_signature=req.do_add_signature,
        do_generate_thumbnail=req.do_generate_thumbnail,
        do_pinned_comment=req.do_pinned_comment if req.do_pinned_comment is not None else bool(pub.get("long_pinned_comment_enabled", False)),
        pinned_comment_text=req.pinned_comment_text if req.pinned_comment_text is not None else str(pub.get("long_pinned_comment_text", "") or ""),
        do_add_to_corpus=req.do_add_to_corpus,
        thumbnail_overlay_title=req.thumbnail_overlay_title,
        thumbnail_overlay_subtitle=req.thumbnail_overlay_subtitle,
        thumbnail_engine=req.thumbnail_engine.strip(),
        steps=[Step(name=n) for n in step_names],
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

    # Manual mode carries over from the meta log so Retry keeps a forced title
    # even when it is omitted; sending "" explicitly returns to AI mode.
    title_override = _validate_manual_title(
        req.title_override if req.title_override is not None else str(meta.get("title_override", "") or ""),
        req.rhythm_silence,
    )
    description_override = str(
        (req.description_override if req.description_override is not None
         else meta.get("description_override", "")) or ""
    ).strip()

    # A manual title needs no transcript, so a run that skipped step 1 can
    # still resume from step 2. Same discovery rules as the pipeline: a
    # sidecar written by another tab counts too.
    if from_step >= 2 and not (title_override and not req.rhythm_silence):
        found = find_transcript(source, files, meta.get("transcript_text", ""))
        if found is None:
            raise HTTPException(
                status_code=400,
                detail="Transcript text not found; cannot resume from step 2+",
            )
        if not files.get("transcript_txt"):
            files["transcript_txt"] = str(found.path)
    if from_step >= 3:
        if not meta.get("title") and not title_override:
            raise HTTPException(status_code=400, detail="Title not found in saved state; cannot resume from thumbnail step")
    if from_step >= 4:
        fv = files.get("final_video", "")
        if not fv or not Path(fv).exists():
            raise HTTPException(status_code=400, detail="Final video not found; cannot resume from step 4+")
    if from_step >= 5:
        if not (files.get("final_video") and Path(files.get("final_video", "")).exists()):
            raise HTTPException(status_code=400, detail="Final video not found; cannot resume from upload")
        if not (meta.get("title") or title_override) or not (meta.get("description") or description_override):
            raise HTTPException(status_code=400, detail="Title/description not found; cannot resume from upload")

    completed_before = set(meta.get("completed_steps", []))
    skipped_before = set(meta.get("skipped_steps", []))

    profile = req.profile or meta.get("profile") or resolve_profile()
    pub = _load_publish_cfg(profile)
    transcript_mode = pub.get("transcript_mode", "normal")
    _validate_rhythm_options(req.rhythm_silence, req.use_modal, transcript_mode, req.do_remove_silence)
    job_id = str(uuid.uuid4())
    step_names = RHYTHM_STEP_NAMES if req.rhythm_silence else STEP_NAMES

    # Step 2 rebuilds both fields when it runs; past it, a manual value
    # supplied now wins over the stored one.
    title = meta.get("title", "")
    description = meta.get("description", "")
    if from_step > 2 and title_override:
        title = title_override
    if from_step > 2 and description_override:
        description = _compose_description(
            req.description_prefix or str(meta.get("description_prefix", "") or ""),
            _validate_urls(req.source_urls) or list(meta.get("source_urls", [])),
            description_override,
            str(pub.get("signature", "")).strip(),
        )

    job = Job(
        job_id=job_id,
        source=source,
        profile=profile,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        do_remove_silence=req.do_remove_silence,
        rhythm_silence=req.rhythm_silence,
        rhythm_params=_job_rhythm_params(pub),
        cut_time=req.cut_time.strip(),
        transcript_mode=transcript_mode,
        language=pub.get("transcript_language", "fr"),
        model=pub.get("transcript_model", "medium"),
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        source_urls=_validate_urls(req.source_urls),
        title_override=title_override,
        description_override=description_override,
        skip_upload=req.skip_upload,
        use_modal=req.use_modal,
        do_normalize_volume=req.do_normalize_volume,
        do_add_signature=req.do_add_signature,
        do_generate_thumbnail=req.do_generate_thumbnail if not req.do_generate_thumbnail else meta.get("do_generate_thumbnail", True),
        do_pinned_comment=req.do_pinned_comment if req.do_pinned_comment is not None else bool(pub.get("long_pinned_comment_enabled", False)),
        pinned_comment_text=req.pinned_comment_text if req.pinned_comment_text is not None else str(pub.get("long_pinned_comment_text", "") or ""),
        do_add_to_corpus=(
            req.do_add_to_corpus
            if req.do_add_to_corpus is not None
            else bool(meta.get("do_add_to_corpus", True))
        ),
        thumbnail_overlay_title=req.thumbnail_overlay_title or meta.get("thumbnail_overlay_title", ""),
        thumbnail_overlay_subtitle=req.thumbnail_overlay_subtitle or meta.get("thumbnail_overlay_subtitle", ""),
        thumbnail_engine=req.thumbnail_engine.strip(),
        steps=[Step(name=n) for n in step_names],
        files=files,
        title=title,
        description=description,
        transcript_text=meta.get("transcript_text", ""),
    )
    job.pinned_comment_id = str(meta.get("pinned_comment_id", "") or "")
    job.pinned_comment_url = str(meta.get("pinned_comment_url", "") or "")
    job.corpus_video_id = str(meta.get("corpus_video_id", "") or "")
    job.corpus_handle = str(meta.get("corpus_handle", "") or "")
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
    meta_exists = _long_meta_path(source).exists()
    next_step = next((i for i in range(len(STEP_NAMES)) if i not in passed), None)
    if not meta_exists:
        next_step = None
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
        "meta_exists": meta_exists,
        "profile": meta.get("profile", ""),
        "next_step": next_step,
        "step_names": STEP_NAMES,
        "available_from_steps": available,
        "completed_steps": sorted(completed),
        "skipped_steps": sorted(skipped),
        "step_files": step_files,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "source_urls": meta.get("source_urls", []),
        "description_prefix": meta.get("description_prefix", ""),
        "title_override": meta.get("title_override", ""),
        "description_override": meta.get("description_override", ""),
        "thumbnail_overlay_title": meta.get("thumbnail_overlay_title", ""),
        "thumbnail_overlay_subtitle": meta.get("thumbnail_overlay_subtitle", ""),
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
    # Same discovery rules as the pipeline, so the Quick prompt box works
    # before a run and reuses a transcript produced by another pipeline.
    found = find_transcript(source, meta.get("files", {}), meta.get("transcript_text", ""))
    transcript_text = found.text if found else ""
    return {
        "title": title,
        "description": description,
        "transcript_text": transcript_text,
        "description_prefix": meta.get("description_prefix", ""),
        "source_urls": meta.get("source_urls", []),
        "title_override": meta.get("title_override", ""),
        "description_override": meta.get("description_override", ""),
        "thumbnail_overlay_title": meta.get("thumbnail_overlay_title", ""),
        "thumbnail_overlay_subtitle": meta.get("thumbnail_overlay_subtitle", ""),
        "video_url": meta.get("video_url", ""),
        "studio_url": meta.get("studio_url", ""),
        "pinned_comment_id": meta.get("pinned_comment_id", ""),
        "pinned_comment_url": meta.get("pinned_comment_url", ""),
        "source": source,
        "final_video": meta.get("files", {}).get("final_video", ""),
        "thumbnail": meta.get("files", {}).get("thumbnail", ""),
    }


# ── Frontend ──────────────────────────────────────────────────────────────────

def register(config: dict) -> WebuxPluginManifest:
    del config
    html = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")
    return WebuxPluginManifest(
        name="long_publish",
        tab_label="YT Long Publish",
        tab_icon="🎬",
        api_router=router,
        frontend_html=html,
        order=46,
        lazy=True,
        busy_check=_is_busy,
    )
