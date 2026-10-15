from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common import structlog
from common.core.config import load_tool_config
from common.webux.base import WebuxPluginManifest

logger = structlog.get_logger(__name__)

router = APIRouter()

#: Same source dir / extensions as long_publish, so both tabs see the same
#: videos and share the per-video ``*-long-meta.json`` thumbnail keys.
DEFAULT_VIDEO_SOURCE_PATH = "/home/joriel/Vidéos"
DEFAULT_VIDEO_EXTENSIONS = "mp4,mkv,webm"

#: Engines with true img2img (init_image) support for the "small changes"
#: edit loop. Cloud engines have no img2img — the current image is sent
#: back as a reference image instead.
IMG2IMG_ENGINES = frozenset({"flux2", "qwen21", "qwen21turbo"})

#: Uploaded/accepted source-image extensions for multi-image compose.
SOURCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _image() -> str:
    return shutil.which("image") or "image"


def _yt() -> str:
    return shutil.which("youtube") or "youtube"


def _publish_cfg() -> dict:
    """Read ``youtube.publish`` (video source dir shared with long_publish)."""
    try:
        cfg = load_tool_config("youtube")
        pub = cfg.get("youtube", {}).get("publish", {})
        return pub if isinstance(pub, dict) else {}
    except Exception:
        return {}


def _image_overlay_defaults() -> dict:
    """Defaults from the image CLI ``overlay:`` config group."""
    try:
        cfg = load_tool_config("image")
        ov = cfg.get("overlay", {}) if isinstance(cfg, dict) else {}
        return ov if isinstance(ov, dict) else {}
    except Exception:
        return {}


def _source_dir() -> Path:
    pub = _publish_cfg()
    d = Path(pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def _extension_set(extensions: str) -> set[str]:
    return {"." + e.strip().lstrip(".").lower() for e in extensions.split(",") if e.strip()}


def _assert_inside(path: Path, root: Path) -> Path:
    """Containment guard: resolved path must live under root (HTTP 403)."""
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail=f"Path escapes {root}: {path}")
    return resolved


def _meta_path(source: Path) -> Path:
    return source.parent / f"{source.stem}-long-meta.json"


def _load_meta(source: Path) -> dict:
    p = _meta_path(source)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _save_meta(source: Path, meta: dict) -> None:
    _meta_path(source).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _parse_generate_output(text: str) -> tuple[str, str]:
    """Parse the JSON block from ``image generate`` / ``image overlay``."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end <= start:
        return "", ""
    try:
        data = json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError, TypeError):
        return "", ""
    return data.get("path", "") or "", data.get("base_path", "") or ""


def _next_version(out_dir: Path, stem: str) -> int:
    versions = []
    for f in out_dir.glob(f"{stem}_thumb_*.*"):
        idx = f.stem.rfind("_thumb_")
        if idx != -1 and f.stem[idx + 7 :].isdigit():
            versions.append(int(f.stem[idx + 7 :]))
    return max(versions, default=0) + 1


def _place_thumb(
    out_dir: Path, stem: str, overlay_path: str, base_path: str, version: int
) -> tuple[str, str]:
    """Rename CLI outputs to ``<stem>_thumb[_overlay]_<N>.<ext>`` in place."""
    new_overlay, new_base = overlay_path, base_path
    if overlay_path and Path(overlay_path).expanduser().exists():
        p = Path(overlay_path).expanduser()
        target = out_dir / f"{stem}_thumb_overlay_{version}{p.suffix}"
        if p.resolve() != target.resolve():
            p.replace(target)
        new_overlay = str(target.resolve())
    if base_path and Path(base_path).expanduser().exists():
        b = Path(base_path).expanduser()
        target = out_dir / f"{stem}_thumb_{version}{b.suffix}"
        if b.resolve() != target.resolve():
            b.replace(target)
        new_base = str(target.resolve())
    return new_overlay, new_base


def _overlay_opts(
    cmd: list[str],
    fg: str = "",
    bg: str = "",
    effect: str = "",
    style: str = "",
    band_size: int = 0,
    size_pct: float = 0,
    offset: int = 0,
    position: str = "",
) -> list[str]:
    """Append overlay flags for non-empty values (empty = image CLI default)."""
    if fg:
        cmd += ["--overlay-fg", fg]
    if bg:
        cmd += ["--overlay-bg", bg]
    if effect:
        cmd += ["--overlay-effect", effect]
    if style:
        cmd += ["--overlay-style", style]
    if band_size:
        cmd += ["--overlay-band-size", str(band_size)]
    if size_pct:
        cmd += ["--overlay-size-pct", str(size_pct)]
    if offset:
        cmd += ["--overlay-offset", str(offset)]
    if position:
        cmd += ["--position", position]
    return cmd


def _resolve_video(source_raw: str, root: Path) -> Path:
    """Resolve + validate a video source inside the source dir."""
    if not (source_raw or "").strip():
        raise HTTPException(status_code=400, detail="Select a video first")
    source = _assert_inside(Path(source_raw.strip()), root)
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")
    return source


def _resolve_image_param(value: str, root: Path) -> Path:
    """Resolve an image path parameter with containment + existence checks."""
    p = _assert_inside(Path(value), root)
    if not p.exists():
        raise HTTPException(status_code=400, detail=f"Image not found: {value}")
    return p


class OverlayOptions(BaseModel):
    fg: str = ""
    bg: str = ""
    effect: str = ""
    style: str = ""
    band_size: int = 0
    size_pct: float = 0
    offset: int = 0
    position: str = ""


class ComposeRequest(BaseModel):
    source: str = ""
    prompt: str = ""
    engine: str = ""
    sources: list[str] = []  # up to 4 reference images (absolute paths)
    seed: int | None = None
    steps: int | None = None
    guidance: float | None = None
    title: str = ""  # overlay text applied at generation time
    overlay: OverlayOptions = OverlayOptions()


class EditRequest(BaseModel):
    source: str = ""
    prompt: str = ""  # the small change, e.g. "warmer background, keep the face"
    base: str = ""  # empty = current thumbnail (else explicit image path)
    engine: str = ""
    strength: float = 0.5  # img2img strength (local engines only)
    seed: int | None = None
    steps: int | None = None
    guidance: float | None = None
    title: str = ""  # re-applied overlay after the edit (empty = keep stored)
    overlay: OverlayOptions = OverlayOptions()


class OverlayRequest(BaseModel):
    source: str = ""
    base: str = ""  # empty = current thumbnail_base (else explicit image path)
    title: str = ""
    overlay: OverlayOptions = OverlayOptions()


class PushRequest(BaseModel):
    source: str = ""
    thumbnail: str = ""


# ── Config / engines / videos ─────────────────────────────────────────────

@router.get("/config")
async def get_config():
    pub = _publish_cfg()
    ov = _image_overlay_defaults()
    return {
        "video_source_path": pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH),
        "video_extensions": pub.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS),
        "thumbnail_engine": pub.get("thumbnail_engine", ""),
        "overlay_defaults": {
            "fg": ov.get("fg", ""),
            "bg": ov.get("bg", ""),
            "effect": ov.get("effect", ""),
            "style": ov.get("style", ""),
            "position": (
                f"{ov.get('vpos', 'bottom')}-{ov.get('hpos', 'center')}"
                if ov.get("vpos") or ov.get("hpos")
                else ""
            ),
        },
    }


@router.get("/list-engines")
async def list_engines():
    try:
        proc = await asyncio.create_subprocess_exec(
            _image(), "setup", "engine", "list", "-f", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode:
            return {"engines": [], "default": ""}
        data = json.loads(stdout.decode(errors="replace"))
        return {
            "engines": data.get("engines", []),
            "default": data.get("default", ""),
        }
    except Exception:
        return {"engines": [], "default": ""}


@router.get("/list-videos")
async def list_videos(
    path: str = Query(default=""),
    extensions: str = Query(default=""),
):
    pub = _publish_cfg()
    root = Path(
        path or pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)
    ).expanduser()
    if not root.exists() or not root.is_dir():
        return {"videos": [], "error": f"Directory not found: {root}"}
    exts = _extension_set(extensions or pub.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS))
    files = sorted(
        (f for f in root.iterdir() if f.is_file() and f.suffix.lower() in exts),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    visible = []
    for f in files:
        meta = _load_meta(f)
        thumb = meta.get("files", {}).get("thumbnail", "") if isinstance(meta.get("files"), dict) else ""
        base = meta.get("files", {}).get("thumbnail_base", "") if isinstance(meta.get("files"), dict) else ""
        visible.append({
            "name": f.name,
            "path": str(f.resolve()),
            "mtime": f.stat().st_mtime,
            "thumbnail": thumb,
            "thumbnail_base": base,
            "video_url": meta.get("video_url", ""),
            "overlay_title": meta.get("thumbnail_overlay_title", ""),
            "prompt": meta.get("thumbnail_prompt", ""),
            "has_thumbnail": bool(thumb and Path(thumb).expanduser().exists()),
        })
    return {"videos": visible}


@router.get("/history")
async def history(source: str = Query(default="")):
    root = _source_dir()
    src = _resolve_video(source, root)
    stem = src.stem
    thumbs = sorted(
        (f for f in src.parent.glob(f"{stem}_thumb_*.*") if f.is_file()),
        key=lambda f: f.stat().st_mtime,
    )
    meta = _load_meta(src)
    return {
        "source": str(src),
        "current": (meta.get("files", {}) or {}).get("thumbnail", ""),
        "base": (meta.get("files", {}) or {}).get("thumbnail_base", ""),
        "versions": [
            {"path": str(f.resolve()), "name": f.name, "mtime": f.stat().st_mtime}
            for f in thumbs
        ],
    }


@router.get("/download")
async def download_file(file: str = Query(...)):
    root = _source_dir()
    p = _resolve_image_param(file, root)
    suffix = p.suffix.lower()
    mime = _IMAGE_MIME.get(suffix, "application/octet-stream")
    if suffix in {".mp4", ".mkv", ".webm", ".mov"}:
        mime = "video/mp4"
    return FileResponse(str(p), media_type=mime, filename=p.name)


# ── Compose / edit / overlay (background jobs with live logs) ─────────────
#
# ``image generate`` can run for 10+ minutes (weight download, denoising),
# so compose/edit/overlay spawn a background asyncio task and return a
# ``job_id`` immediately. The task streams the subprocess stderr into the
# job log line-by-line; the frontend polls ``GET /job/{id}`` and renders a
# live console. Fast validation failures (400s) still raise synchronously.

_jobs: dict[str, dict] = {}

_JOB_LOG_MAX_LINES = 500
_JOB_LOG_MAX_LINE = 400
_MAX_JOBS = 20


def _new_job(action: str, source: str) -> str:
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        "job_id": job_id,
        "action": action,
        "source": source,
        "status": "running",  # running | done | error
        "log": [],
        "result": None,
        "error": "",
        "done": asyncio.Event(),
    }
    # Prune oldest finished jobs so the dict stays small.
    finished = [j for j in _jobs.values() if j["status"] != "running"]
    for old in sorted(finished, key=lambda j: j["job_id"])[: max(0, len(finished) - _MAX_JOBS)]:
        _jobs.pop(old["job_id"], None)
    return job_id


def _job_log(job_id: str, line: str) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    line = line.rstrip()
    if len(line) > _JOB_LOG_MAX_LINE:
        line = line[:_JOB_LOG_MAX_LINE] + "…"
    job["log"].append(line)
    del job["log"][: -_JOB_LOG_MAX_LINES]


def _finish_job(job_id: str, result: dict | None = None, error: str = "") -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    if error:
        job["status"] = "error"
        job["error"] = error
        _job_log(job_id, f"FAILED: {error}")
        logger.error("yt_thumbnail_job_failed", job_id=job_id, error=error)
    else:
        job["status"] = "done"
        job["result"] = result or {}
        _job_log(job_id, "Done.")
    job["done"].set()


async def _run_and_log(job_id: str, cmd: list[str]) -> str:
    """Spawn ``cmd``, stream its stderr into the job log, return stdout.

    Raises RuntimeError (recorded in the log) when the process fails.
    The full command line is logged with the prompt truncated — prompts
    can be long and secrets must never appear (no secrets are passed).
    """
    shown = [c if len(c) < 80 else c[:77] + "…" for c in cmd]
    _job_log(job_id, "$ " + " ".join(shown))
    started = asyncio.get_running_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    async def _drain() -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            _job_log(job_id, line.decode(errors="replace"))

    await asyncio.gather(proc.wait(), _drain())
    stdout = (await proc.stdout.read()).decode(errors="replace")
    elapsed = asyncio.get_running_loop().time() - started
    _job_log(job_id, f"(process exited code={proc.returncode} in {elapsed:.1f}s)")
    if proc.returncode:
        tail = "\n".join(_jobs[job_id]["log"][-5:]).strip()
        raise RuntimeError(tail or f"Exit code {proc.returncode}")
    return stdout


@router.get("/job/{job_id}")
async def job_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job["job_id"],
        "action": job["action"],
        "source": job["source"],
        "status": job["status"],
        "log": "\n".join(job["log"]),
        "result": job["result"],
        "error": job["error"],
    }


def _update_meta_after(
    source: Path, new_path: str, new_base: str, version: int,
    prompt: str = "", overlay_title: str = "",
) -> dict:
    meta = _load_meta(source)
    files = dict(meta.get("files", {}) or {})
    files["thumbnail"] = new_path
    if new_base:
        files["thumbnail_base"] = new_base
    meta["files"] = files
    meta["thumbnail_version"] = version
    if prompt:
        meta["thumbnail_prompt"] = prompt
    if overlay_title:
        meta["thumbnail_overlay_title"] = overlay_title
    _save_meta(source, meta)
    return meta


@router.post("/compose")
async def compose(req: ComposeRequest):
    """Start a compose job (returns ``{"job_id"}`` immediately).

    Poll ``GET /job/{id}`` for the live console log and the final
    ``{"thumbnail", "base", "version"}`` result.
    """
    root = _source_dir()
    source = _resolve_video(req.source, root)
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="A prompt is required to compose")
    refs = []
    for s in (req.sources or [])[:4]:
        p = _resolve_image_param(s, root)
        if p.suffix.lower() not in SOURCE_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Not an image: {s}")
        refs.append(str(p))

    job_id = _new_job("compose", str(source))
    asyncio.create_task(_compose_worker(job_id, req, source, refs))
    logger.info(
        "yt_thumbnail_compose_start",
        job_id=job_id, source=str(source),
        engine=req.engine.strip(), refs=len(refs), text_only=not refs,
    )
    return {"job_id": job_id}


async def _compose_worker(
    job_id: str, req: ComposeRequest, source: Path, refs: list[str]
) -> None:
    try:
        prompt = (req.prompt or "").strip()
        out_dir = source.parent
        stem = source.stem
        version = _next_version(out_dir, stem)
        ov = req.overlay
        cmd = [
            _image(), "generate", prompt,
            "--size", "youtube", "-F", "json", "-v",
            "--output-dir", str(out_dir),
        ]
        for r in refs:
            cmd += ["-R", r]
        if req.engine.strip():
            cmd += ["--engine", req.engine.strip()]
        if req.seed is not None:
            cmd += ["--seed", str(req.seed)]
        if req.steps is not None:
            cmd += ["--steps", str(req.steps)]
        if req.guidance is not None:
            cmd += ["--guidance-scale", str(req.guidance)]
        if req.title.strip():
            cmd += ["--title", req.title.strip()]
        cmd = _overlay_opts(
            cmd, ov.fg.strip(), ov.bg.strip(), ov.effect.strip(), ov.style.strip(),
            ov.band_size, ov.size_pct, ov.offset, ov.position.strip(),
        )
        _job_log(
            job_id,
            f"compose: engine={req.engine.strip() or '(image default)'} "
            f"refs={len(refs)} size=youtube",
        )
        stdout = await _run_and_log(job_id, cmd)
        new_path, new_base = _parse_generate_output(stdout)
        if not new_path or not Path(new_path).expanduser().exists():
            raise RuntimeError("output path not found in command output")
        new_path, new_base = _place_thumb(out_dir, stem, new_path, new_base, version)
        _update_meta_after(source, new_path, new_base, version, prompt, req.title.strip())
        _finish_job(
            job_id,
            {"thumbnail": new_path, "base": new_base, "version": version},
        )
    except Exception as exc:
        _finish_job(job_id, error=str(exc))


@router.post("/edit")
async def edit(req: EditRequest):
    """Start a small-change edit job (returns ``{"job_id"}`` immediately).

    Local engines (flux2, qwen21, qwen21turbo) use img2img
    (``--init-image`` + ``--strength``); cloud engines receive the image
    back as a ``-R`` reference since they have no img2img.
    """
    root = _source_dir()
    source = _resolve_video(req.source, root)
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Describe the small change to apply")
    meta = _load_meta(source)
    files = dict(meta.get("files", {}) or {})

    if req.base.strip():
        base = str(_resolve_image_param(req.base.strip(), root))
    else:
        base = files.get("thumbnail", "") or files.get("thumbnail_base", "")
        if not base or not Path(base).expanduser().exists():
            raise HTTPException(
                status_code=400,
                detail="No current thumbnail to edit; compose one first",
            )
        base = str(Path(base).expanduser().resolve())

    job_id = _new_job("edit", str(source))
    asyncio.create_task(_edit_worker(job_id, req, source, base))
    logger.info(
        "yt_thumbnail_edit_start", job_id=job_id,
        source=str(source), engine=req.engine.strip(),
    )
    return {"job_id": job_id}


async def _edit_worker(
    job_id: str, req: EditRequest, source: Path, base: str
) -> None:
    try:
        prompt = (req.prompt or "").strip()
        engine = req.engine.strip()
        meta = _load_meta(source)
        out_dir = source.parent
        stem = source.stem
        version = _next_version(out_dir, stem)
        ov = req.overlay
        overlay_title = req.title.strip() or meta.get("thumbnail_overlay_title", "").strip()

        cmd = [_image(), "generate", prompt, "--size", "youtube", "-F", "json", "-v",
               "--output-dir", str(out_dir)]
        if engine:
            cmd += ["--engine", engine]
        if req.seed is not None:
            cmd += ["--seed", str(req.seed)]
        if req.steps is not None:
            cmd += ["--steps", str(req.steps)]
        if req.guidance is not None:
            cmd += ["--guidance-scale", str(req.guidance)]
        # img2img when the engine supports it, else reference-image fallback.
        use_img2img = (not engine) or (engine in IMG2IMG_ENGINES)
        if use_img2img:
            cmd += ["--init-image", base, "--strength", str(req.strength)]
        else:
            cmd += ["-R", base]
        if overlay_title:
            cmd += ["--title", overlay_title]
        cmd = _overlay_opts(
            cmd, ov.fg.strip(), ov.bg.strip(), ov.effect.strip(), ov.style.strip(),
            ov.band_size, ov.size_pct, ov.offset, ov.position.strip(),
        )
        _job_log(
            job_id,
            f"edit: engine={engine or '(image default)'} "
            f"mode={'img2img' if use_img2img else 'reference'}",
        )
        stdout = await _run_and_log(job_id, cmd)
        new_path, new_base = _parse_generate_output(stdout)
        if not new_path or not Path(new_path).expanduser().exists():
            raise RuntimeError("output path not found in command output")
        new_path, new_base = _place_thumb(out_dir, stem, new_path, new_base, version)
        _update_meta_after(source, new_path, new_base or base, version, prompt, overlay_title)
        _finish_job(
            job_id,
            {
                "thumbnail": new_path, "base": new_base or base,
                "version": version, "mode": "img2img" if use_img2img else "reference",
            },
        )
    except Exception as exc:
        _finish_job(job_id, error=str(exc))


@router.post("/overlay")
async def overlay(req: OverlayRequest):
    """Start an overlay job (returns ``{"job_id"}`` immediately).

    (Re)applies overlay text on the base image — same style as long_publish.
    """
    root = _source_dir()
    source = _resolve_video(req.source, root)
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Provide an overlay title")
    meta = _load_meta(source)
    files = dict(meta.get("files", {}) or {})

    if req.base.strip():
        base = str(_resolve_image_param(req.base.strip(), root))
    else:
        base = files.get("thumbnail_base", "") or files.get("thumbnail", "")
        if not base or not Path(base).expanduser().exists():
            raise HTTPException(
                status_code=400,
                detail="No base image available; compose or upload one first",
            )
        base = str(Path(base).expanduser().resolve())

    job_id = _new_job("overlay", str(source))
    asyncio.create_task(_overlay_worker(job_id, req, source, base, title))
    logger.info("yt_thumbnail_overlay_start", job_id=job_id, source=str(source))
    return {"job_id": job_id}


async def _overlay_worker(
    job_id: str, req: OverlayRequest, source: Path, base: str, title: str
) -> None:
    try:
        meta = _load_meta(source)
        out_dir = source.parent
        stem = source.stem
        version = int(meta.get("thumbnail_version", 0) or 0)
        ov = req.overlay
        cmd = [_image(), "overlay", base, "--title", title, "-F", "json"]
        cmd = _overlay_opts(
            cmd, ov.fg.strip(), ov.bg.strip(), ov.effect.strip(), ov.style.strip(),
            ov.band_size, ov.size_pct, ov.offset, ov.position.strip(),
        )
        _job_log(job_id, f"overlay: {title!r}")
        stdout = await _run_and_log(job_id, cmd)
        new_path, _ = _parse_generate_output(stdout)
        if not new_path or not Path(new_path).expanduser().exists():
            raise RuntimeError("output path not found in command output")
        # Overlay reuses the current version slot (same base, new text).
        new_path, renamed_base = _place_thumb(out_dir, stem, new_path, base, version or 1)
        _update_meta_after(source, new_path, renamed_base or base, version or 1,
                           overlay_title=title)
        _finish_job(job_id, {"thumbnail": new_path, "base": renamed_base or base})
    except Exception as exc:
        _finish_job(job_id, error=str(exc))


@router.post("/upload-sources")
async def upload_sources(
    source: str = Form(""),
    files: list[UploadFile] = File(...),
):
    """Upload up to 4 source images for multi-image compose.

    Stored next to the video as ``<stem>_src_<k>.<ext>`` (image extensions
    never match the video file lists, so the folder stays clean).
    """
    root = _source_dir()
    src = _resolve_video(source, root) if source.strip() else None
    stem = src.stem if src is not None else "shared"
    out_dir = src.parent if src is not None else root

    saved: list[str] = []
    for i, upload in enumerate((files or [])[:4]):
        ext = Path(upload.filename or "").suffix.lower() or ".png"
        if ext not in SOURCE_EXTENSIONS:
            raise HTTPException(
                status_code=400, detail=f"Unsupported image format: {upload.filename}"
            )
        target = out_dir / f"{stem}_src_{i}{ext}"
        if target.exists():
            target = out_dir / f"{stem}_src_{i}_{uuid.uuid4().hex[:6]}{ext}"
        with open(target, "wb") as f:
            f.write(await upload.read())
        saved.append(str(target.resolve()))
    if not saved:
        raise HTTPException(status_code=400, detail="No files uploaded")
    return {"sources": saved}


@router.post("/push-thumbnail")
async def push_thumbnail(req: PushRequest):
    """Push the current (or given) thumbnail to YouTube for this video."""
    root = _source_dir()
    source = _resolve_video(req.source, root)
    meta = _load_meta(source)
    thumb = req.thumbnail.strip() or (meta.get("files", {}) or {}).get("thumbnail", "")
    if not thumb or not Path(thumb).expanduser().exists():
        raise HTTPException(status_code=400, detail="No thumbnail available to push")
    video_url = meta.get("video_url", "")
    video_id = _extract_video_id(video_url)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="No YouTube video ID found for this source; cannot push thumbnail",
        )
    thumb = str(Path(thumb).expanduser().resolve())
    cmd = [_yt(), "thumbnail-set", video_id, "--file", thumb]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        err = stderr.decode(errors="replace").strip()
        raise HTTPException(status_code=500, detail=err or f"Exit code {proc.returncode}")
    return {"ok": True, "video_id": video_id}


def _extract_video_id(url: str) -> str:
    """Extract a YouTube video ID from common URL forms (mirrors long_publish)."""
    import re as _re

    if not url:
        return ""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"youtube\.com.*[?&]v=([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = _re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


# ── Frontend ──────────────────────────────────────────────────────────────────

def register(config: dict) -> WebuxPluginManifest:
    del config
    html = (Path(__file__).parent / "frontend.html").read_text(encoding="utf-8")
    return WebuxPluginManifest(
        name="yt_thumbnail",
        tab_label="YT Thumbnail",
        tab_icon="🖼️",
        api_router=router,
        frontend_html=html,
        order=47,
        lazy=True,
        group="Publish",
    )
