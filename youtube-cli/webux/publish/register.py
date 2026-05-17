from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest
from common.core.config import load_tool_config, save_tool_config

router = APIRouter()

# ── Pipeline state ────────────────────────────────────────────────────────────

STEP_NAMES = [
    "Remove silence",
    "Extract transcript",
    "Burn subtitles",
    "Generate title & description",
    "Upload to YouTube",
]

DEFAULT_VIDEO_SOURCE_PATH = "/home/joriel/Vidéos"
DEFAULT_VIDEO_EXTENSIONS = "mp4,mkv"


@dataclass
class Step:
    name: str
    status: str = "pending"   # pending | running | done | error | skipped
    output: str = ""


@dataclass
class Job:
    job_id: str
    source: str
    prompt_title: str
    prompt_summary: str
    do_remove_silence: bool
    do_burn_subtitles: bool
    language: str
    model: str
    privacy: str
    description_prefix: str = ""
    steps: list[Step] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    title: str = ""
    description: str = ""
    status: str = "running"
    video_url: str = ""
    studio_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "video_url": self.video_url,
            "studio_url": self.studio_url,
            "title": self.title,
            "description": self.description,
            "files": self.files,
            "steps": [
                {"name": s.name, "status": s.status, "output": s.output}
                for s in self.steps
            ],
        }


_jobs: dict[str, Job] = {}


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_publish_cfg() -> dict:
    try:
        cfg = load_tool_config("youtube")
        return cfg.get("youtube", {}).get("publish", {})
    except Exception:
        return {}


def _save_publish_cfg(pub: dict) -> None:
    try:
        cfg = load_tool_config("youtube")
        yt = cfg.setdefault("youtube", {})
        yt["publish"] = pub
        save_tool_config("youtube", cfg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _yt() -> str:
    return shutil.which("youtube") or "youtube"


def _pr() -> str:
    return shutil.which("prompt") or "prompt"


def _stem(p: str) -> str:
    return Path(p).stem


def _dir(p: str) -> Path:
    return Path(p).resolve().parent


def _extract_video_id(url: str) -> str:
    """Extract YouTube video ID from a watch URL."""
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


def _ass_to_plain_text(ass_path: str) -> str:
    """Strip ASS tags and headers; return dialogue lines as plain text."""
    lines = []
    with open(ass_path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue
            text = parts[9].strip()
            text = re.sub(r"\{[^}]*\}", "", text)
            if text:
                lines.append(text)
    return "\n".join(lines)


def _get_video_duration(path: str) -> float:
    """Return video duration in seconds via ffprobe."""
    import subprocess
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


async def _run(step: Step, *cmd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    step.output = (out + "\n" + err).strip()
    return proc.returncode or 0, out


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _run_pipeline(job: Job) -> None:
    stem = _stem(job.source)
    d = _dir(job.source)

    current_video = job.source

    # Step 0 — Remove silence
    s0 = job.steps[0]
    if job.do_remove_silence:
        s0.status = "running"
        out_path = str(d / f"{stem}_nosilence.mp4")
        rc, _ = await _run(s0, _yt(), "remove-silence", job.source, "-o", out_path)
        if rc != 0:
            s0.status = "error"
            job.status = "error"
            return
        duration = _get_video_duration(out_path)
        if duration > 180:
            s0.status = "error"
            s0.output += f"\n⏱ Video is {duration:.0f}s — exceeds 180s limit for YouTube Shorts."
            job.status = "error"
            return
        s0.status = "done"
        s0.output += f"\n⏱ Duration: {duration:.0f}s"
        current_video = out_path
        job.files["no_silence"] = out_path
    else:
        s0.status = "skipped"

    # Step 1 — Extract transcript (faster-whisper → ASS karaoke)
    s1 = job.steps[1]
    s1.status = "running"
    ass_path = str(d / f"{stem}.ass")
    txt_path = str(d / f"{stem}_transcript.txt")
    rc, _ = await _run(
        s1, _yt(), "extract-transcript", current_video,
        "-o", ass_path, "-l", job.language, "-m", job.model,
    )
    if rc != 0:
        s1.status = "error"
        job.status = "error"
        return
    s1.status = "done"
    job.files["transcript"] = ass_path
    # Write plain-text version for LLM (ASS tags stripped)
    plain = _ass_to_plain_text(ass_path)
    with open(txt_path, "w", encoding="utf-8") as _f:
        _f.write(plain)
    job.files["transcript_txt"] = txt_path

    # Step 2 — Burn subtitles
    s2 = job.steps[2]
    if job.do_burn_subtitles:
        s2.status = "running"
        out_path = str(d / f"{stem}_subtitled.mp4")
        rc, _ = await _run(
            s2, _yt(), "burn-subtitles", current_video, ass_path, "-o", out_path
        )
        if rc != 0:
            s2.status = "error"
            job.status = "error"
            return
        s2.status = "done"
        current_video = out_path
        job.files["subtitled"] = out_path
    else:
        s2.status = "skipped"

    job.files["final_video"] = current_video
    await _run_from_llm(job, txt_path, current_video)


async def _run_from_llm(job: Job, transcript_path: str, final_video: str) -> None:
    """Resumable entry point: run LLM step then upload."""
    # Step 3 — Prompt apply
    s3 = job.steps[3]
    s3.status = "running"

    rc, title_out = await _run(s3, _pr(), "apply", job.prompt_title, f"transcript=@{transcript_path}")
    if rc != 0:
        s3.status = "error"
        job.status = "error"
        return

    proc = await asyncio.create_subprocess_exec(
        _pr(), "apply", job.prompt_summary, f"transcript=@{transcript_path}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    desc_out, desc_err = await proc.communicate()
    if proc.returncode:
        s3.output += "\n" + desc_err.decode(errors="replace")
        s3.status = "error"
        job.status = "error"
        return

    raw_description = desc_out.decode(errors="replace").strip()

    # Apply description prefix (top) and signature (bottom)
    pub_cfg = _load_publish_cfg()
    signature = pub_cfg.get("signature", "").strip()

    parts = []
    if job.description_prefix.strip():
        parts.append(job.description_prefix.strip())
    parts.append(raw_description)
    if signature:
        parts.append(signature)

    job.title = title_out.strip()
    job.description = "\n\n".join(parts)
    s3.output = f"Title: {job.title[:80]}"
    s3.status = "done"

    # Step 4 — Upload
    s4 = job.steps[4]
    s4.status = "running"
    rc, url_out = await _run(
        s4, _yt(), "upload", final_video,
        "--title", job.title,
        "--description", job.description,
        "--privacy", job.privacy,
    )
    if rc != 0:
        s4.status = "error"
        job.status = "error"
        return

    s4.status = "done"
    watch_url = url_out.strip()
    video_id = _extract_video_id(watch_url)
    if video_id:
        job.video_url = f"https://www.youtube.com/shorts/{video_id}"
        job.studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
    else:
        job.video_url = watch_url
        job.studio_url = ""
    job.status = "done"


# ── Config API ────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    pub = _load_publish_cfg()
    return {
        "video_source_path": pub.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH),
        "video_extensions": pub.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS),
        "signature": pub.get("signature", ""),
    }


class ConfigSaveRequest(BaseModel):
    video_source_path: str = DEFAULT_VIDEO_SOURCE_PATH
    video_extensions: str = DEFAULT_VIDEO_EXTENSIONS
    signature: str = ""


@router.post("/config")
async def save_config(req: ConfigSaveRequest):
    pub = _load_publish_cfg()
    pub["video_source_path"] = req.video_source_path
    pub["video_extensions"] = req.video_extensions
    pub["signature"] = req.signature
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
        [f for f in d.iterdir() if f.suffix.lower() in exts],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return {
        "videos": [
            {"name": f.name, "path": str(f), "mtime": f.stat().st_mtime}
            for f in files
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


@router.post("/upload-external")
async def upload_external(file: UploadFile = File(...)):
    """Accept external file upload and save to temp dir. Return path for use as source."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".mkv", ".mov", ".webm"}:
        raise HTTPException(status_code=400, detail="Unsupported video format")
    dest = Path(tempfile.gettempdir()) / f"webux_upload_{uuid.uuid4().hex}{ext}"
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
    language: str = "fr"
    model: str = "medium"
    privacy: str = "unlisted"
    description_prefix: str = ""


class ResumeRequest(BaseModel):
    source: str
    prompt_title: str
    prompt_summary: str
    privacy: str = "unlisted"
    description_prefix: str = ""


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
        language=req.language,
        model=req.model,
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    _jobs[job_id] = job
    asyncio.create_task(_run_pipeline(job))
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
    d = _dir(source)
    stem = _stem(source)
    ass_path = str(d / f"{stem}.ass")
    if not Path(ass_path).exists():
        raise HTTPException(status_code=400, detail=f"Transcript not found: {ass_path}")

    # Derive/regenerate plain-text for LLM
    txt_path = str(d / f"{stem}_transcript.txt")
    if not Path(txt_path).exists():
        plain = _ass_to_plain_text(ass_path)
        with open(txt_path, "w", encoding="utf-8") as _f:
            _f.write(plain)

    final_video = source
    for candidate in [
        str(d / f"{stem}_subtitled.mp4"),
        str(d / f"{stem}_nosilence.mp4"),
        source,
    ]:
        if Path(candidate).exists():
            final_video = candidate
            break

    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        source=source,
        prompt_title=req.prompt_title,
        prompt_summary=req.prompt_summary,
        do_remove_silence=False,
        do_burn_subtitles=False,
        language="fr",
        model="medium",
        privacy=req.privacy,
        description_prefix=req.description_prefix,
        steps=[Step(name=n) for n in STEP_NAMES],
        files={"transcript": ass_path, "transcript_txt": txt_path, "final_video": final_video},
    )
    for i in range(3):
        job.steps[i].status = "skipped"
    _jobs[job_id] = job
    asyncio.create_task(_run_from_llm(job, txt_path, final_video))
    return {"job_id": job_id}


@router.post("/check-resume")
async def check_resume(body: dict):
    source = str(Path(body.get("source", "")).expanduser().resolve())
    ass = _dir(source) / f"{_stem(source)}.ass"
    return {"can_resume": ass.exists(), "transcript": str(ass)}


# ── Frontend ──────────────────────────────────────────────────────────────────

_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Publish</title>
  <style>
    :root {
      --bg:#1a1a2e; --bg2:#16213e; --text:#eee; --dim:#888;
      --accent:#0f3460; --ok:#4ade80; --err:#f87171; --warn:#fbbf24; --border:#333;
      --link:#7dd3fc;
    }
    body { margin:0; padding:16px; background:var(--bg); color:var(--text);
           font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
    .wrap { max-width:860px; margin:0 auto; }
    h2 { margin:0 0 12px; font-size:18px; }
    label { display:block; font-size:12px; color:var(--dim); margin-bottom:3px; }
    input[type=text], select, textarea {
      width:100%; padding:7px 10px; border:1px solid var(--border);
      background:var(--bg2); color:var(--text); border-radius:6px;
      box-sizing:border-box; font-size:13px;
    }
    textarea { resize:vertical; }
    .row { margin-bottom:10px; }
    .cols2 { display:flex; gap:12px; }
    .cols2 .row { flex:1; }
    .checkrow { display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:13px; }
    button { padding:7px 14px; border:none; border-radius:6px; cursor:pointer; font-size:13px; font-weight:600; }
    .btn-go     { background:var(--ok); color:#000; }
    .btn-go:hover { opacity:.88; }
    .btn-go:disabled { opacity:.4; cursor:default; }
    .btn-resume { background:var(--warn); color:#000; display:none; }
    .btn-resume:hover { opacity:.88; }
    .btn-sec    { background:var(--accent); color:var(--text); }
    .btn-sec:hover { opacity:.88; }
    /* two-column main layout */
    .main-layout { display:flex; gap:16px; align-items:flex-start; }
    .main-left { flex:1; min-width:0; }
    .main-right { flex:0 0 260px; }
    .video-wrap { border:1px solid var(--border); border-radius:8px; overflow:hidden;
                  background:#000; display:none; }
    .video-wrap video { width:100%; height:220px; object-fit:contain; display:block; }
    .video-name { font-size:11px; color:var(--dim); padding:4px 8px;
                  background:var(--bg2); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    /* pipeline */
    .steps { margin:14px 0 10px; }
    .step { display:flex; align-items:flex-start; gap:10px; padding:6px 0;
            border-bottom:1px solid var(--border); font-size:13px; }
    .step:last-child { border-bottom:none; }
    .step-icon { width:20px; flex-shrink:0; font-size:14px; margin-top:1px; }
    .step-name { flex:1; }
    .step-out { font-size:11px; color:var(--dim); margin-top:2px; word-break:break-all; }
    .step-out.collapsed { display:none; }
    .step-toggle { cursor:pointer; font-size:10px; color:var(--dim); margin-left:6px;
                   user-select:none; opacity:.7; }
    .step-toggle:hover { opacity:1; }
    .log-box { background:#0f172a; border:1px solid var(--border); border-radius:8px;
               padding:10px; font-size:12px; font-family:monospace; white-space:pre-wrap;
               max-height:160px; overflow-y:auto; margin-top:10px; display:none; }
    .result { margin-top:12px; padding:12px; border-radius:8px;
              background:var(--bg2); border:1px solid var(--ok); display:none; }
    .result-title { font-size:15px; font-weight:700; margin-bottom:6px; }
    .result-desc { font-size:12px; color:var(--dim); white-space:pre-wrap; max-height:110px;
                   overflow-y:auto; border:1px solid var(--border); border-radius:4px;
                   padding:8px; background:#0f172a; margin-bottom:8px; }
    .result-links { display:flex; flex-direction:column; gap:5px; }
    .result-links a { color:var(--link); font-size:13px; word-break:break-all; }
    .hint { font-size:11px; color:var(--dim); margin-left:8px; }
    hr { border:none; border-top:1px solid var(--border); margin:12px 0; }
    /* config */
    .config-toggle { cursor:pointer; color:var(--dim); font-size:12px; margin-bottom:8px; user-select:none; }
    .config-panel { display:none; padding:10px; border:1px solid var(--border);
                    border-radius:6px; background:var(--bg2); margin-bottom:12px; }
    .file-row { display:flex; gap:8px; align-items:flex-end; }
    .file-row input { flex:1; }
  </style>
</head>
<body>
<div class="wrap">
  <h2>🚀 Publish</h2>

  <!-- Config panel -->
  <div class="config-toggle" id="configToggle">⚙️ YouTube Publish Settings ▼</div>
  <div class="config-panel" id="configPanel">
    <div class="cols2">
      <div class="row">
        <label>Video source directory</label>
        <div class="file-row">
          <input type="text" id="sourceDir" placeholder="/home/joriel/Vidéos" />
          <button class="btn-sec" onclick="scanDir()">Scan</button>
        </div>
      </div>
      <div class="row">
        <label>File extensions (comma-separated)</label>
        <input type="text" id="videoExtensions" value="mp4,mkv" placeholder="mp4,mkv" />
      </div>
    </div>
    <div class="row">
      <label>Signature (appended to every description)</label>
      <textarea id="signature" rows="3" placeholder="Your signature / links..."></textarea>
    </div>
    <button class="btn-sec" onclick="saveConfig()">💾 Save settings</button>
    <span id="configStatus" style="font-size:12px;margin-left:8px;color:var(--ok);display:none">Saved!</span>
  </div>

  <div class="main-layout">
    <!-- Left: form -->
    <div class="main-left">
      <!-- Source video -->
      <div class="row">
        <label>Source video</label>
        <select id="fileSelect" onchange="onFileSelected()">
          <option value="">— select a video —</option>
        </select>
        <div id="dropZone" style="margin-top:6px;border:2px dashed var(--border);border-radius:6px;padding:12px;text-align:center;font-size:13px;color:var(--dim);cursor:pointer;">
          or drag &amp; drop external file here
        </div>
      </div>

      <!-- Prompts -->
      <div class="cols2">
        <div class="row">
          <label>Prompt — title</label>
          <input type="text" id="promptTitle" list="promptsList" placeholder="youtube-title" />
        </div>
        <div class="row">
          <label>Prompt — description</label>
          <input type="text" id="promptSummary" list="promptsList" placeholder="youtube-summary" />
        </div>
      </div>
      <datalist id="promptsList"></datalist>

      <!-- Description prefix -->
      <div class="row">
        <label>Description prefix (added at the top)</label>
        <textarea id="descPrefix" rows="2" placeholder="Optional text to prepend..."></textarea>
      </div>

      <!-- Options row -->
      <div class="cols2" style="align-items:flex-end">
        <div class="row" style="flex:0 0 auto">
          <label>Language</label>
          <input type="text" id="language" value="fr" style="width:55px" />
        </div>
        <div class="row" style="flex:0 0 auto">
          <label>Whisper model</label>
          <input type="text" id="model" value="medium" style="width:100px" />
        </div>
        <div class="row" style="flex:0 0 auto">
          <label>Privacy</label>
          <select id="privacy" style="width:100px">
            <option value="unlisted" selected>unlisted</option>
            <option value="private">private</option>
            <option value="public">public</option>
          </select>
        </div>
      </div>
      <div class="checkrow"><input type="checkbox" id="doSilence" checked /><span>Remove silence</span></div>
      <div class="checkrow"><input type="checkbox" id="doBurn" checked /><span>Burn subtitles</span></div>

      <div style="display:flex;gap:10px;align-items:center;margin-top:10px">
        <button class="btn-go" id="startBtn">▶ Publish</button>
        <button class="btn-resume" id="resumeBtn">↩ Resume</button>
        <span class="hint" id="resumeHint"></span>
      </div>
    </div>

    <!-- Right: video preview -->
    <div class="main-right">
      <div class="video-wrap" id="videoWrap">
        <video id="videoPreview" controls preload="metadata"></video>
        <div class="video-name" id="videoName"></div>
      </div>
    </div>
  </div>

  <hr />

  <div class="steps" id="stepsEl">
    <div class="step" id="step-0"><span class="step-icon">⬜</span><div style="flex:1"><div class="step-name">Remove silence<span class="step-toggle" id="toggle-0" onclick="toggleOut(0)">▶ logs</span></div><div class="step-out collapsed" id="out-0"></div></div></div>
    <div class="step" id="step-1"><span class="step-icon">⬜</span><div><div class="step-name">Extract transcript (faster-whisper)</div><div class="step-out" id="out-1"></div></div></div>
    <div class="step" id="step-2"><span class="step-icon">⬜</span><div style="flex:1"><div class="step-name">Burn subtitles<span class="step-toggle" id="toggle-2" onclick="toggleOut(2)">▶ logs</span></div><div class="step-out collapsed" id="out-2"></div></div></div>
    <div class="step" id="step-3"><span class="step-icon">⬜</span><div><div class="step-name">Generate title &amp; description</div><div class="step-out" id="out-3"></div></div></div>
    <div class="step" id="step-4"><span class="step-icon">⬜</span><div><div class="step-name">Upload to YouTube</div><div class="step-out" id="out-4"></div></div></div>
  </div>

  <!-- Result -->
  <div class="result" id="result">
    <div class="result-title" id="resultTitle"></div>
    <div class="result-desc" id="resultDesc"></div>
    <div class="result-links">
      <a id="resultShortUrl" href="#" target="_blank"></a>
      <a id="resultStudioUrl" href="#" target="_blank"></a>
    </div>
  </div>
  <div class="log-box" id="logBox"></div>
</div>

<script>
const ICONS = { pending:'⬜', running:'🔄', done:'✅', error:'❌', skipped:'⏭️' };
let pollTimer = null;
let jobId = null;
let selectedFilePath = '';

// ── Config ────────────────────────────────────────────────────────────────────

document.getElementById('configToggle').addEventListener('click', () => {
  const panel = document.getElementById('configPanel');
  const toggle = document.getElementById('configToggle');
  const open = panel.style.display === 'block';
  panel.style.display = open ? 'none' : 'block';
  toggle.textContent = (open ? '▼' : '▲').replace(/[▼▲]/, open ? '▼' : '▲');
  toggle.textContent = '⚙️ YouTube Publish Settings ' + (open ? '▼' : '▲');
});

async function loadConfig() {
  const r = await fetch('/api/publish/config').catch(() => null);
  if (!r || !r.ok) return;
  const data = await r.json();
  document.getElementById('sourceDir').value = data.video_source_path || '/home/joriel/Vidéos';
  document.getElementById('videoExtensions').value = data.video_extensions || 'mp4,mkv';
  document.getElementById('signature').value = data.signature || '';
  await scanDir();
}

async function saveConfig() {
  const r = await fetch('/api/publish/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_source_path: document.getElementById('sourceDir').value.trim(),
      video_extensions: document.getElementById('videoExtensions').value.trim() || 'mp4,mkv',
      signature: document.getElementById('signature').value,
    }),
  }).catch(() => null);
  const st = document.getElementById('configStatus');
  st.style.display = 'inline';
  if (r && r.ok) {
    st.textContent = 'Saved!';
    st.style.color = 'var(--ok)';
  } else {
    st.textContent = 'Error saving';
    st.style.color = 'var(--err)';
  }
  setTimeout(() => { st.style.display = 'none'; }, 2000);
}

// ── Video list ─────────────────────────────────────────────────────────────────

async function scanDir() {
  const dir = document.getElementById('sourceDir').value.trim() || '/home/joriel/Vidéos';
  const ext = document.getElementById('videoExtensions').value.trim() || 'mp4,mkv';
  const r = await fetch(
    '/api/publish/list-videos?path=' + encodeURIComponent(dir) + '&extensions=' + encodeURIComponent(ext)
  ).catch(() => null);
  const sel = document.getElementById('fileSelect');
  sel.innerHTML = '<option value="">— select a video —</option>';
  if (!r || !r.ok) return;
  const data = await r.json();
  if (data.videos && data.videos.length) {
    data.videos.forEach((v, i) => {
      const opt = document.createElement('option');
      opt.value = v.path;
      opt.textContent = v.name;
      sel.appendChild(opt);
    });
    // Select most recent (first) by default
    sel.value = data.videos[0].path;
    onFileSelected();
  }
}

function onFileSelected() {
  const path = document.getElementById('fileSelect').value;
  selectedFilePath = path;
  const wrap = document.getElementById('videoWrap');
  const video = document.getElementById('videoPreview');
  const nameEl = document.getElementById('videoName');
  if (path) {
    video.src = '/api/publish/video-preview?file=' + encodeURIComponent(path);
    nameEl.textContent = path.split('/').pop();
    wrap.style.display = 'block';
    checkResume();
  } else {
    wrap.style.display = 'none';
    video.src = '';
    nameEl.textContent = '';
  }
}

// ── Prompts ────────────────────────────────────────────────────────────────────

async function loadPrompts() {
  const r = await fetch('/api/publish/list-prompts').catch(() => null);
  if (!r || !r.ok) return;
  const data = await r.json();
  const prompts = data.prompts || [];
  const dl = document.getElementById('promptsList');
  dl.innerHTML = '';
  prompts.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    dl.appendChild(opt);
  });
  const ptEl = document.getElementById('promptTitle');
  const psEl = document.getElementById('promptSummary');
  if (!ptEl.value && prompts.includes('youtube-title'))   ptEl.value = 'youtube-title';
  if (!psEl.value && prompts.includes('youtube-summary')) psEl.value = 'youtube-summary';
}

// ── Pipeline UI ────────────────────────────────────────────────────────────────

function renderSteps(steps) {
  steps.forEach((s, i) => {
    const icon = document.querySelector('#step-' + i + ' .step-icon');
    const out  = document.getElementById('out-' + i);
    if (icon) icon.textContent = ICONS[s.status] || '⬜';
    if (out)  out.textContent  = s.output || '';
  });
}

function toggleOut(i) {
  const out = document.getElementById('out-' + i);
  const tog = document.getElementById('toggle-' + i);
  if (!out || !tog) return;
  const willCollapse = !out.classList.contains('collapsed');
  out.classList.toggle('collapsed');
  tog.textContent = willCollapse ? '▶ logs' : '▼ logs';
}

function log(msg) {
  const box = document.getElementById('logBox');
  box.style.display = 'block';
  box.textContent += msg + '\\n';
  box.scrollTop = box.scrollHeight;
}

function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

function resetUI() {
  stopPoll(); jobId = null;
  document.getElementById('result').style.display   = 'none';
  document.getElementById('logBox').style.display   = 'none';
  document.getElementById('logBox').textContent     = '';
  document.getElementById('resumeBtn').style.display = 'none';
  document.getElementById('resumeHint').textContent  = '';
  for (let i = 0; i < 5; i++) {
    document.querySelector('#step-' + i + ' .step-icon').textContent = '⬜';
    const out = document.getElementById('out-' + i);
    out.textContent = '';
    if (i === 0 || i === 2) {
      out.classList.add('collapsed');
      const tog = document.getElementById('toggle-' + i);
      if (tog) tog.textContent = '▶ logs';
    }
  }
}

async function poll() {
  if (!jobId) return;
  const r = await fetch('/api/publish/status/' + jobId).catch(() => null);
  if (!r || !r.ok) return;
  const data = await r.json();
  renderSteps(data.steps);
  if (data.status === 'done') {
    stopPoll();
    document.getElementById('startBtn').disabled = false;
    // Show result
    const res = document.getElementById('result');
    document.getElementById('resultTitle').textContent = '✅ ' + (data.title || 'Published!');
    document.getElementById('resultDesc').textContent  = data.description || '';
    const shortEl = document.getElementById('resultShortUrl');
    const studioEl = document.getElementById('resultStudioUrl');
    if (data.video_url) {
      shortEl.href = data.video_url;
      shortEl.textContent = '📱 ' + data.video_url;
    }
    if (data.studio_url) {
      studioEl.href = data.studio_url;
      studioEl.textContent = '📊 ' + data.studio_url;
    }
    res.style.display = 'block';
  } else if (data.status === 'error') {
    stopPoll();
    document.getElementById('startBtn').disabled = false;
    checkResume();
  }
}

async function checkResume() {
  const src = selectedFilePath || document.getElementById('fileSelect').value;
  if (!src) return;
  const r = await fetch('/api/publish/check-resume', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ source: src }),
  }).catch(() => null);
  if (!r || !r.ok) return;
  const data = await r.json();
  if (data.can_resume) {
    document.getElementById('resumeBtn').style.display = 'inline-block';
    document.getElementById('resumeHint').textContent  = data.transcript;
  }
}

async function launch(isResume) {
  const src  = selectedFilePath || document.getElementById('fileSelect').value;
  const pt   = document.getElementById('promptTitle').value.trim();
  const ps   = document.getElementById('promptSummary').value.trim();
  const priv = document.getElementById('privacy').value;
  const desc_prefix = document.getElementById('descPrefix').value;
  if (!src)       { alert('Select a source video.'); return; }
  if (!pt || !ps) { alert('Fill in both prompt names.'); return; }

  resetUI();
  document.getElementById('startBtn').disabled = true;

  const url  = isResume ? '/api/publish/resume' : '/api/publish/start';
  const body = isResume
    ? { source:src, prompt_title:pt, prompt_summary:ps, privacy:priv, description_prefix:desc_prefix }
    : {
        source:src, prompt_title:pt, prompt_summary:ps, privacy:priv,
        description_prefix: desc_prefix,
        do_remove_silence: document.getElementById('doSilence').checked,
        do_burn_subtitles: document.getElementById('doBurn').checked,
        language: document.getElementById('language').value.trim() || 'fr',
        model:    document.getElementById('model').value.trim() || 'medium',
      };

  const r = await fetch(url, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body),
  }).catch(e => { log('Error: ' + e.message); document.getElementById('startBtn').disabled = false; return null; });
  if (!r) return;
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail:'Failed' }));
    log('Error: ' + (err.detail || 'Failed'));
    document.getElementById('startBtn').disabled = false;
    return;
  }
  const data = await r.json();
  jobId = data.job_id;
  log('Job: ' + jobId);
  pollTimer = setInterval(poll, 2000);
}

document.getElementById('startBtn').addEventListener('click', () => launch(false));
document.getElementById('resumeBtn').addEventListener('click', () => launch(true));

// ── Init ───────────────────────────────────────────────────────────────────────

loadConfig();
loadPrompts();

// ── Drag & drop external upload ──────────────────────────────────────────────
const dropZone = document.getElementById('dropZone');
dropZone.addEventListener('click', () => {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = 'video/*';
  inp.onchange = () => { if (inp.files[0]) uploadExternal(inp.files[0]); };
  inp.click();
});
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.style.borderColor = 'var(--accent)'; });
dropZone.addEventListener('dragleave', () => { dropZone.style.borderColor = 'var(--border)'; });
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.style.borderColor = 'var(--border)';
  if (e.dataTransfer.files.length) uploadExternal(e.dataTransfer.files[0]);
});

async function uploadExternal(file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch('/api/publish/upload-external', { method: 'POST', body: fd }).catch(() => null);
  if (!r || !r.ok) { alert('Upload failed'); return; }
  const data = await r.json();
  // Add to select and pick it
  const sel = document.getElementById('fileSelect');
  const opt = document.createElement('option');
  opt.value = data.path;
  opt.textContent = data.name + ' (uploaded)';
  sel.appendChild(opt);
  sel.value = data.path;
  onFileSelected();
}
</script>
</body>
</html>
"""


def register(config: dict) -> WebuxPluginManifest:
    del config
    return WebuxPluginManifest(
        name="publish",
        tab_label="Publish",
        tab_icon="🚀",
        api_router=router,
        frontend_html=_HTML,
        order=45,
        lazy=True,
    )
