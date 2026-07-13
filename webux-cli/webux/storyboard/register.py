from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest

from .config import load_storyboard_config, save_storyboard_config
from .models import ProjectState, StepState, SCENE_STEPS
from .pipeline import (
    start_pipeline, stop_pipeline, is_running,
    get_current_state, _find_scene, GLOBAL_TO_SCENE_STEP,
)

router = APIRouter()

# ── State helpers ─────────────────────────────────────────────────────────────

def _state_path(config: dict) -> Path:
    workdir = config.get("workdir") or ""
    if not workdir:
        raise HTTPException(status_code=400, detail="workdir not set in common config — run toolsetup")
    return Path(workdir).expanduser() / "storyboard" / "state.json"


def _load_state(config: dict) -> ProjectState | None:
    sp = _state_path(config)
    if not sp.exists():
        return None
    try:
        return ProjectState.load(sp)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load state: {exc}")


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    cfg = load_storyboard_config()
    return {
        "tts_engine": cfg.get("tts_engine", "kokoro"),
        "language": cfg.get("language", "en"),
        "image_engine": cfg.get("image_engine", "flux2cloud"),
        "image_size": cfg.get("image_size", "landscape"),
        "image_style": cfg.get("image_style", ""),
        "narrative_style": cfg.get("narrative_style", ""),
        "animation_style": cfg.get("animation_style", "ken_burns"),
        "ken_burns_zoom_from": cfg.get("ken_burns_zoom_from", 1.0),
        "ken_burns_zoom_to": cfg.get("ken_burns_zoom_to", 1.3),
        "ken_burns_motion": cfg.get("ken_burns_motion", "random"),
        "fps": cfg.get("fps", 24),
        "image_seed": cfg.get("image_seed"),
        "image_steps": cfg.get("image_steps"),
        "draft_mode": cfg.get("draft_mode", False),
        "draft_steps": cfg.get("draft_steps", 1),
        "chapter_transition": cfg.get("chapter_transition", "none"),
        "chapter_transition_duration": cfg.get("chapter_transition_duration", 1.0),
        "chapter_range": cfg.get("chapter_range", "2–5"),
        "scene_range": cfg.get("scene_range", "2–5"),
        "scene_duration": cfg.get("scene_duration", "15–45 seconds"),
        "prompts": cfg.get("prompts", {}),
        "prompt_overrides": cfg.get("prompt_overrides", {}),
    }


class ConfigSaveRequest(BaseModel):
    tts_engine: str = "kokoro"
    language: str = "en"
    image_engine: str = "flux2cloud"
    image_size: str = "landscape"
    image_style: str = ""
    narrative_style: str = ""
    animation_style: str = "ken_burns"
    ken_burns_zoom_from: float = 1.0
    ken_burns_zoom_to: float = 1.3
    ken_burns_motion: str = "random"
    fps: int = 24
    image_seed: int | None = None
    image_steps: int | None = None
    draft_mode: bool = False
    draft_steps: int = 1
    chapter_transition: str = "none"
    chapter_transition_duration: float = 1.0
    chapter_range: str = "2–5"
    scene_range: str = "2–5"
    scene_duration: str = "15–45 seconds"
    prompts: dict = {}
    prompt_overrides: dict = {}


@router.post("/config")
async def save_config(req: ConfigSaveRequest):
    save_storyboard_config(req.model_dump())
    return {"ok": True}


@router.get("/list-prompts")
async def list_prompts():
    pr = shutil.which("prompt") or "prompt"
    proc = await asyncio.create_subprocess_exec(
        pr, "list", "--names-only",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    names = [n.strip() for n in stdout.decode(errors="replace").splitlines() if n.strip()]
    return {"prompts": names}


@router.get("/prompt-content")
async def prompt_content(name: str = Query(...)):
    pr = shutil.which("prompt") or "prompt"
    proc = await asyncio.create_subprocess_exec(
        pr, "get", name, "--content",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return {"name": name, "content": stdout.decode(errors="replace").strip()}


@router.get("/state")
async def get_state():
    cfg = load_storyboard_config()
    state = _load_state(cfg)
    if state is None:
        return {"initialized": False}
    return {"initialized": True, **state.to_dict(), "global_steps": state.global_step_summary()}


class InitRequest(BaseModel):
    script_text: str


@router.post("/init")
async def init_project(req: InitRequest):
    if not req.script_text.strip():
        raise HTTPException(status_code=400, detail="Script text is empty")

    cfg = load_storyboard_config()
    sp = _state_path(cfg)
    workdir = str(sp.parent)

    Path(workdir).mkdir(parents=True, exist_ok=True)

    state = ProjectState(script_text=req.script_text, workdir=workdir)
    state.save(sp)
    return {"initialized": True, **state.to_dict(), "global_steps": state.global_step_summary()}


class RunRequest(BaseModel):
    from_global_step: str | None = None
    only_global_step: str | None = None
    scene_id: str | None = None
    from_step: str | None = None
    only_step: bool = False
    only_scene: bool = False  # run within scene only, don't cascade to chapter/final


@router.post("/run")
async def run_pipeline(req: RunRequest):
    if is_running():
        raise HTTPException(status_code=409, detail="Pipeline already running")
    cfg = load_storyboard_config()
    state = _load_state(cfg)
    if state is None:
        raise HTTPException(status_code=400, detail="Project not initialized — call /init first")
    sp = _state_path(cfg)
    start_pipeline(state, sp, cfg,
                   from_global_step=req.from_global_step,
                   only_global_step=req.only_global_step,
                   scene_id=req.scene_id,
                   from_step=req.from_step,
                   only_step=req.only_step,
                   only_scene=req.only_scene)
    return {"ok": True, "running": True}


@router.post("/stop")
async def stop():
    stop_pipeline()
    return {"ok": True}


@router.get("/job")
async def poll_job():
    cfg = load_storyboard_config()
    running = is_running()
    live_state = get_current_state()
    if live_state is not None:
        return {
            "running": running,
            "initialized": True,
            **live_state.to_dict(),
            "global_steps": live_state.global_step_summary(),
        }
    state = _load_state(cfg)
    if state is None:
        return {"running": False, "initialized": False}
    return {
        "running": running,
        "initialized": True,
        **state.to_dict(),
        "global_steps": state.global_step_summary(),
    }


class SceneUpdateRequest(BaseModel):
    transcript: str | None = None
    image_prompt: str | None = None


@router.post("/scene/{scene_id}")
async def update_scene(scene_id: str, req: SceneUpdateRequest):
    """Save edited transcript or image_prompt for a scene (persists to disk)."""
    cfg = load_storyboard_config()
    state = _load_state(cfg)
    if state is None:
        raise HTTPException(status_code=400, detail="Project not initialized")
    sc = _find_scene(state, scene_id)
    if sc is None:
        raise HTTPException(status_code=404, detail=f"Scene not found: {scene_id}")
    ch_id = scene_id.rsplit("_sc", 1)[0]
    scene_dir = Path(state.workdir) / "chapters" / ch_id / "scenes" / scene_id
    if req.transcript is not None:
        sc.transcript = req.transcript
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "transcript.txt").write_text(sc.transcript, encoding="utf-8")
    if req.image_prompt is not None:
        sc.image_prompt = req.image_prompt
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "image_prompt.txt").write_text(sc.image_prompt, encoding="utf-8")
    state.save(_state_path(cfg))
    return {"ok": True}


@router.post("/script")
async def update_script(body: dict):
    """Update the script text and reset parse state."""
    text = body.get("script_text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="script_text is empty")
    cfg = load_storyboard_config()
    state = _load_state(cfg)
    if state is None:
        raise HTTPException(status_code=400, detail="Project not initialized")
    from .models import StepState
    state.script_text = text
    state.parse_step = StepState()
    state.chapters = []
    state.save(_state_path(cfg))
    return {"ok": True}


_MIME = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@router.get("/preview")
async def preview_file(file: str = Query(...)):
    p = Path(file).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {p}")
    mime = _MIME.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=mime)


@router.get("/download")
async def download_file(file: str = Query(...)):
    p = Path(file).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {p}")
    return FileResponse(str(p), filename=p.name)


# ── Frontend HTML ─────────────────────────────────────────────────────────────

_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Storyboard</title>
<style>
:root {
  --bg: #1e1e2e; --bg2: #181825; --bg3: #11111b;
  --surface: #313244; --surface2: #45475a;
  --text: #cdd6f4; --text-dim: #6c7086; --text-muted: #9399b2;
  --accent: #89b4fa; --accent2: #74c7ec;
  --green: #a6e3a1; --red: #f38ba8; --yellow: #f9e2af; --orange: #fab387;
  --border: #313244;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg3); color: var(--text); font-family: system-ui, sans-serif; font-size: 13px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* ── Top bar ── */
.topbar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--bg2); border-bottom: 1px solid var(--border); flex-shrink: 0; flex-wrap: wrap; }
.topbar input[type=text] { flex: 1; min-width: 200px; background: var(--bg3); border: 1px solid var(--surface2); border-radius: 4px; padding: 5px 8px; color: var(--text); font-size: 12px; }
.topbar input[type=text]::placeholder { color: var(--text-dim); }
.btn { padding: 5px 12px; border-radius: 4px; border: none; cursor: pointer; font-size: 12px; font-weight: 600; transition: opacity .15s; }
.btn:disabled { opacity: .4; cursor: default; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-danger { background: var(--red); color: #fff; }
.btn-neutral { background: var(--surface); color: var(--text); }
.btn-sm { padding: 3px 8px; font-size: 11px; border-radius: 3px; border: none; cursor: pointer; font-weight: 500; }
.btn-sm:disabled { opacity: .4; cursor: default; }
.status-badge { font-size: 11px; padding: 3px 8px; border-radius: 12px; font-weight: 600; }
.s-idle { background: var(--surface); color: var(--text-muted); }
.s-running { background: var(--accent); color: #fff; }
.s-done { background: var(--green); color: #1e1e2e; }
.s-error { background: var(--red); color: #fff; }
.s-partial { background: var(--yellow); color: #1e1e2e; }
.topbar-sep { color: var(--text-dim); }
.workdir-label { color: var(--text-dim); font-size: 11px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Main layout ── */
.main-layout { display: flex; flex: 1; overflow: hidden; }

/* ── Left sidebar: global steps ── */
.sidebar { width: 200px; background: var(--bg2); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; overflow-y: auto; }
.sidebar-title { padding: 10px 12px 6px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--text-dim); }
.gstep { display: flex; align-items: center; gap: 8px; padding: 6px 12px; cursor: pointer; border-radius: 4px; margin: 0 4px; transition: background .1s; }
.gstep:hover { background: var(--surface); }
.gstep .gstep-icon { font-size: 14px; width: 18px; text-align: center; }
.gstep .gstep-name { flex: 1; font-size: 12px; }
.gstep .gstep-run { font-size: 10px; color: var(--accent); visibility: hidden; }
.gstep:hover .gstep-run { visibility: visible; }

/* ── Right content ── */
.content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* ── Collapsible panels ── */
.panel-hdr { display: flex; align-items: center; gap: 8px; padding: 4px 8px; background: var(--bg2); border-bottom: 1px solid var(--border); font-size: 11px; font-weight: 600; color: var(--text-dim); flex-shrink: 0; cursor: pointer; user-select: none; }
.panel-hdr:hover { background: var(--surface); }
.ph-toggle { margin-left: auto; font-size: 10px; }
.panel-collapsed > .panel-bdy { display: none !important; }
.panel-collapsed { flex: 0 0 28px !important; max-height: 28px !important; overflow: hidden !important; }
.dur-badge { font-size: 10px; color: var(--accent); margin-left: 4px; opacity: .8; }
.stats-bar { font-size: 10px; color: var(--text-dim); padding: 4px 8px; border-bottom: 1px solid var(--border); display: flex; gap: 12px; flex-shrink: 0; }
.stats-bar b { color: var(--text); }

/* ── Scene tree ── */
.tree-panel { flex: 2 1 180px; overflow: hidden; display: flex; flex-direction: column; border-bottom: 1px solid var(--border); }
.tree-panel > .panel-bdy { flex: 1; overflow-y: auto; padding: 8px; }
.no-state { padding: 24px; text-align: center; color: var(--text-dim); }
.chapter-node { margin-bottom: 4px; }
.chapter-header { display: flex; align-items: center; gap: 6px; padding: 5px 8px; background: var(--surface); border-radius: 4px; cursor: pointer; user-select: none; }
.chapter-header:hover { background: var(--surface2); }
.chapter-toggle { font-size: 10px; color: var(--text-dim); width: 12px; }
.chapter-title { flex: 1; font-weight: 600; font-size: 12px; }
.chapter-status { font-size: 11px; }
.scene-list { padding: 2px 0 2px 16px; }
.scene-row { display: flex; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 4px; cursor: pointer; }
.scene-row:hover { background: var(--surface); }
.scene-row.selected { background: var(--surface); border-left: 2px solid var(--accent); }
.scene-title { flex: 1; font-size: 12px; }
.step-dots { display: flex; gap: 3px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--surface2); }
.dot.done { background: var(--green); }
.dot.running { background: var(--accent); animation: pulse .8s infinite; }
.dot.error { background: var(--red); }
.dot.skipped { background: var(--text-dim); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

/* ── Detail panel ── */
.detail-panel { flex: 3 1 200px; overflow: hidden; display: flex; flex-direction: column; }
.detail-panel > .panel-bdy { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.detail-title { font-size: 14px; font-weight: 700; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.detail-tabs { display: flex; gap: 4px; }
.dtab { padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; background: var(--surface); color: var(--text-muted); }
.dtab.active { background: var(--accent); color: #fff; font-weight: 600; }
.dtab-content { display: none; }
.dtab-content.active { display: flex; flex-direction: column; gap: 6px; }
/* ── View mode toggle ── */
.view-toggle { display: flex; gap: 4px; padding: 6px 10px; border-bottom: 1px solid var(--border); background: var(--bg2); flex-shrink: 0; }
.vtab { padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; background: var(--surface); color: var(--text-muted); border: none; }
.vtab.active { background: var(--accent); color: #fff; font-weight: 600; }
/* ── Format view panel ── */
.format-panel { display: none; flex: 1; overflow: hidden; flex-direction: column; min-height: 0; }
.format-panel.visible { display: flex; }
.format-tabs { display: flex; gap: 4px; padding: 8px 12px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.format-body { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 16px; }
.format-scene-block { background: var(--bg2); border: 1px solid var(--border); border-radius: 6px; padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.format-scene-title { font-size: 12px; font-weight: 700; color: var(--accent); }
.format-scene-chapter { font-size: 10px; color: var(--text-dim); }
audio.fmt-audio { width: 100%; max-width: 600px; }
img.fmt-img { max-width: 480px; max-height: 270px; border-radius: 4px; border: 1px solid var(--border); cursor: pointer; }
video.fmt-vid { max-width: 480px; max-height: 270px; border-radius: 4px; border: 1px solid var(--border); }
/* ── Matrix view panel ── */
.matrix-panel { display: none; flex: 1; overflow: hidden; flex-direction: column; min-height: 0; }
.matrix-panel.visible { display: flex; }
.matrix-body { flex: 1; overflow: auto; padding: 12px; }
.matrix-tbl { width: 100%; border-collapse: collapse; table-layout: fixed; }
.matrix-tbl th { font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: .06em; padding: 6px 10px; border-bottom: 2px solid var(--border); text-align: left; background: var(--bg2); position: sticky; top: 0; z-index: 1; }
.matrix-tbl td { vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--border); }
.matrix-tbl tr:hover td { background: var(--bg2); }
.matrix-col-scene { width: 140px; }
.matrix-col-image { width: 210px; }
.matrix-col-audio { width: 200px; }
.matrix-col-video { width: 210px; }
.matrix-scene-chapter { font-size: 10px; color: var(--text-dim); margin-bottom: 2px; }
.matrix-scene-title { font-size: 12px; font-weight: 700; color: var(--accent); cursor: pointer; }
.matrix-scene-title:hover { text-decoration: underline; }
.matrix-scene-dots { display: flex; gap: 3px; margin-top: 6px; }
.matrix-full-text { font-size: 11px; color: var(--text-muted); font-family: monospace; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
.matrix-empty { font-size: 11px; color: var(--text-dim); font-style: italic; }
img.matrix-img { max-width: 190px; border-radius: 4px; border: 1px solid var(--border); cursor: pointer; display: block; }
audio.matrix-audio { width: 100%; }
video.matrix-video { max-width: 190px; border-radius: 4px; border: 1px solid var(--border); display: block; }
.detail-row { display: flex; align-items: center; gap: 6px; }
.detail-label { font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: .06em; }
textarea.edit-area { width: 100%; background: var(--bg2); border: 1px solid var(--border); border-radius: 4px; padding: 6px 8px; color: var(--text); font-size: 12px; font-family: monospace; resize: vertical; min-height: 80px; }
.save-hint { font-size: 11px; color: var(--text-dim); }
.media-row { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
audio { width: 100%; max-width: 400px; }
img.scene-img { max-width: 320px; max-height: 180px; border-radius: 4px; border: 1px solid var(--border); cursor: pointer; }
video.scene-vid { max-width: 320px; max-height: 180px; border-radius: 4px; border: 1px solid var(--border); }
.step-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 6px; }
.step-card { background: var(--bg2); border: 1px solid var(--border); border-radius: 4px; padding: 8px; }
.step-card-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.step-card-name { font-size: 11px; font-weight: 600; }
.step-card-log { font-size: 10px; color: var(--text-muted); font-family: monospace; max-height: 60px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
.step-rerun { font-size: 10px; }

/* ── Script modal ── */
.modal-overlay { position: fixed; inset: 0; background: rgba(17,17,27,.85); display: none; align-items: center; justify-content: center; z-index: 20; }
.modal-overlay.open { display: flex; }
.modal-card { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 20px 24px; width: min(680px, 95vw); max-height: 85vh; display: flex; flex-direction: column; gap: 10px; }
.modal-title { font-size: 14px; font-weight: 700; color: var(--accent); }
.modal-card textarea { flex: 1; min-height: 300px; background: var(--bg3); border: 1px solid var(--border); border-radius: 4px; padding: 8px; color: var(--text); font-size: 12px; font-family: monospace; resize: none; }
.modal-footer { display: flex; gap: 8px; justify-content: flex-end; }

/* ── Error banner ── */
.error-banner { display: none; background: var(--red); color: #fff; padding: 6px 12px; font-size: 12px; font-weight: 600; flex-shrink: 0; }
.error-banner.visible { display: block; }

/* ── Console panel ── */
.console-panel { flex: 0 0 180px; background: var(--bg3); border-top: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
.console-panel.panel-collapsed { flex: 0 0 28px !important; }
.console-panel.panel-collapsed .console-body { display: none !important; }
.console-header { display: flex; align-items: center; gap: 8px; padding: 4px 8px; background: var(--bg2); border-bottom: 1px solid var(--border); font-size: 11px; font-weight: 600; color: var(--text-dim); flex-shrink: 0; cursor: pointer; user-select: none; }
.console-header:hover { background: var(--surface); }
.console-body { flex: 1; overflow-y: auto; font-family: monospace; font-size: 10px; padding: 4px 8px; }
/* ── Final panel ── */
.final-panel { flex-shrink: 0; overflow: hidden; display: flex; flex-direction: column; border-top: 1px solid var(--border); }
.final-panel.panel-collapsed { flex: 0 0 28px !important; max-height: 28px !important; }
.final-panel.panel-collapsed > .panel-bdy { display: none !important; }
.final-panel > .panel-bdy { padding: 10px; overflow-y: auto; }
.regen-group { display: flex; gap: 3px; align-items: center; padding: 0 4px; border-left: 1px solid var(--border); border-right: 1px solid var(--border); margin: 0 2px; }
.regen-group .btn-sm { padding: 3px 8px; background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.regen-group .btn-sm:disabled { opacity: .35; cursor: default; }
.regen-group .btn-sm:not(:disabled):hover { background: var(--bg2); }
.final-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
.final-header { font-size: 12px; font-weight: 600; color: var(--text-dim); margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.console-entry { margin-bottom: 4px; border-bottom: 1px solid var(--bg2); padding-bottom: 3px; }
.console-cmd { color: var(--accent2); }
.console-ok { color: var(--text-muted); white-space: pre-wrap; word-break: break-all; }
.console-err { color: var(--red); white-space: pre-wrap; word-break: break-all; }
.console-ts { color: var(--text-dim); }

/* ── Sidebar step run buttons ── */
.gstep-actions { display: flex; gap: 2px; opacity: 0; transition: opacity .1s; }
.gstep:hover .gstep-actions { opacity: 1; }
.gstep-btn { font-size: 9px; padding: 1px 5px; border-radius: 3px; border: none; cursor: pointer; background: var(--surface2); color: #fff; }
.gstep-btn:hover { background: var(--accent); }

/* ── Config panel ── */
.config-panel { flex-shrink: 0; background: var(--bg2); border-top: 1px solid var(--border); }
.config-toggle { display: flex; align-items: center; gap: 6px; padding: 6px 12px; cursor: pointer; user-select: none; font-size: 12px; font-weight: 600; color: var(--text-dim); }
.config-toggle:hover { color: var(--text); }
.config-toggle .arrow { font-size: 10px; transition: transform .2s; }
.config-toggle.open .arrow { transform: rotate(180deg); }
.config-body { display: none; padding: 10px 12px; border-top: 1px solid var(--border); max-height: 280px; overflow-y: auto; }
.config-body.open { display: block; }
.cfg-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.cfg-field { display: flex; flex-direction: column; gap: 3px; }
.cfg-label { font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: .06em; }
.cfg-field input, .cfg-field select, .cfg-field textarea { background: var(--bg3); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; color: var(--text); font-size: 12px; }
.cfg-field textarea { resize: vertical; min-height: 60px; font-family: monospace; }
.cfg-prompts { margin-top: 10px; }
.prompt-field { margin-top: 8px; }
.prompt-label { font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 3px; }
.prompt-area { width: 100%; background: var(--bg3); border: 1px solid var(--border); border-radius: 4px; padding: 6px 8px; color: var(--text); font-size: 11px; font-family: monospace; resize: vertical; min-height: 80px; }
.prompt-sel { width: 100%; background: var(--bg3); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; color: var(--text); font-size: 12px; margin-bottom: 4px; }
.prompt-info { cursor: help; color: #fff; font-weight: 400; text-transform: none; letter-spacing: 0; }
.prompt-info:hover::after {
  content: attr(data-content);
  position: absolute;
  left: 8px; right: 8px;
  margin-top: 4px;
  display: block;
  white-space: pre-wrap;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px;
  font-size: 11px;
  font-family: monospace;
  color: var(--text);
  z-index: 50;
  max-height: 320px;
  overflow: auto;
}

/* ── Init overlay ── */
.init-overlay { position: absolute; inset: 0; background: rgba(17,17,27,.9); display: flex; align-items: center; justify-content: center; z-index: 10; }
.init-card { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 24px 28px; max-width: 540px; width: 94%; text-align: center; }
.init-card h2 { margin-bottom: 6px; font-size: 18px; color: var(--accent); }
.init-card p { color: var(--text-dim); font-size: 12px; margin-bottom: 12px; }
.init-textarea { width: 100%; min-height: 160px; background: var(--bg3); border: 1px solid var(--surface2); border-radius: 4px; padding: 8px; color: var(--text); font-size: 12px; font-family: monospace; resize: vertical; margin-bottom: 12px; }
</style>
</head>
<body>

<!-- Script edit modal -->
<div class="modal-overlay" id="scriptModal" onclick="if(event.target===this)closeScriptModal()">
  <div class="modal-card">
    <div class="modal-title">📄 Script</div>
    <textarea id="scriptModalText" placeholder="Paste your script here..."></textarea>
    <div class="modal-footer">
      <button class="btn btn-neutral" onclick="closeScriptModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveScript()">Save &amp; Reset Parse</button>
    </div>
  </div>
</div>

<!-- Init overlay (shown when no project) -->
<div class="init-overlay" id="initOverlay">
  <div class="init-card">
    <h2>📽 Storyboard</h2>
    <p>Paste your script below (markdown format). Each section will become a chapter.</p>
    <textarea class="init-textarea" id="initScriptText" placeholder="# My Story&#10;&#10;## Chapter 1: The Beginning&#10;&#10;An exciting introduction...&#10;&#10;## Chapter 2: The Rising Action&#10;&#10;..."></textarea>
    <button class="btn btn-primary" onclick="initProject()">Create Project</button>
    <p id="initError" style="color:var(--red);margin-top:10px;font-size:12px;"></p>
  </div>
</div>

<!-- Top bar -->
<div class="topbar">
  <span style="font-size:15px;">📽</span>
  <strong style="font-size:13px;color:var(--accent);">Storyboard</strong>
  <span class="topbar-sep">|</span>
  <span class="workdir-label" id="workdirLabel">…</span>
  <span class="topbar-sep">|</span>
  <button class="btn btn-neutral" id="btnScript" onclick="showScriptModal()" disabled>📄 Script</button>
  <button class="btn btn-primary" id="btnRunAll" onclick="runAll()" disabled>▶ Run All</button>
  <span class="regen-group">
    <span style="font-size:10px;color:var(--text-dim)">Regen:</span>
    <button class="btn-sm" id="btnRegenAudio" onclick="regenStep('audio')" disabled title="Re-generate all audio (only_step)">🔊 Audio</button>
    <button class="btn-sm" id="btnRegenImage" onclick="regenStep('image')" disabled title="Re-generate all images (only_step)">🖼 Image</button>
    <button class="btn-sm" id="btnRegenClip"  onclick="regenStep('clip')"  disabled title="Re-assemble all clips (only_step)">🎬 Clips</button>
    <button class="btn-sm" id="btnRegenFinal" onclick="regenMerge()" disabled title="Re-run chapter merges then rebuild final video">📽 Merge</button>
  </span>
  <button class="btn btn-neutral" id="btnStop" onclick="stopPipeline()" disabled>⏹ Stop</button>
  <span class="status-badge s-idle" id="statusBadge">idle</span>
  <span style="flex:1"></span>
  <button class="btn btn-neutral" onclick="resetProject()" title="Reset / change script">⟳ Reset</button>
</div>

<!-- Error banner -->
<div class="error-banner" id="errorBanner">⚠ Pipeline error — expand a step below to see the output</div>

<!-- Main layout -->
<div class="main-layout">

  <!-- Left sidebar: global pipeline steps -->
  <aside class="sidebar">
    <div class="sidebar-title">Pipeline</div>
    <div id="globalSteps">
      <!-- rendered by JS -->
    </div>
  </aside>

  <!-- Content: tree + detail + console -->
  <div class="content">

    <!-- View mode toggle -->
    <div class="view-toggle">
      <button class="vtab active" id="vtabChapter" onclick="setViewMode('chapter')">📋 Chapter</button>
      <button class="vtab" id="vtabFormat" onclick="setViewMode('format')">📄 Format</button>
      <button class="vtab" id="vtabMatrix" onclick="setViewMode('matrix')">🔲 Matrix</button>
    </div>

    <!-- Matrix view panel (hidden by default) -->
    <div class="matrix-panel" id="matrixPanel">
      <div class="matrix-body">
        <div id="matrixTable"></div>
      </div>
    </div>

    <!-- Format view panel (hidden by default) -->
    <div class="format-panel" id="formatPanel">
      <div class="format-tabs">
        <button class="dtab active" id="ftabTranscript" onclick="setFormatTab('transcript')">📝 Transcripts</button>
        <button class="dtab" id="ftabAudio"      onclick="setFormatTab('audio')">🔊 Audio</button>
        <button class="dtab" id="ftabImage"      onclick="setFormatTab('image')">🖼 Images</button>
        <button class="dtab" id="ftabClip"       onclick="setFormatTab('clip')">🎬 Clips</button>
      </div>
      <div class="format-body" id="formatBody"></div>
    </div>

    <div class="tree-panel" id="treePanel">
      <div class="panel-hdr" onclick="togglePanel('treePanel')">
        📋 Chapters
        <span id="statsBar" style="flex:1;font-weight:400;color:var(--text-dim);font-size:10px;margin-left:6px"></span>
        <span class="ph-toggle" id="treeToggle">▾</span>
      </div>
      <div class="panel-bdy" id="treeBody">
        <div class="no-state">Loading…</div>
      </div>
    </div>
    <div class="detail-panel" id="detailPanel">
      <div class="panel-hdr" onclick="togglePanel('detailPanel')">
        🔍 Scene Detail
        <span class="ph-toggle" id="detailToggle">▾</span>
      </div>
      <div class="panel-bdy" id="detailBody">
        <div class="no-state" style="color:var(--text-dim)">Select a scene to view details.</div>
      </div>
    </div>
    <div class="console-panel" id="consolePanel">
      <div class="console-header" onclick="togglePanel('consolePanel')">
        ⌨ Console
        <button class="btn-sm" onclick="event.stopPropagation();clearConsoleDisplay()" style="background:var(--surface);color:var(--text)">Clear</button>
        <span class="ph-toggle" id="consolePanelToggle">▾</span>
      </div>
      <div class="console-body" id="consoleBody"><span style="color:var(--text-dim)">Commands will appear here...</span></div>
    </div>
    <div class="final-panel" id="finalPanel" style="display:none">
      <div class="panel-hdr" onclick="togglePanel('finalPanel')">
        📽 Final Video
        <span id="finalStatus" style="font-size:10px;color:var(--green);font-weight:400"></span>
        <span class="ph-toggle" id="finalToggle">▾</span>
      </div>
      <div class="panel-bdy" id="finalBody">
        <video id="finalVideo" controls style="width:100%;max-height:280px;border-radius:4px;background:#000;display:block"></video>
        <div style="margin-top:6px;display:flex;gap:8px;align-items:center">
          <a id="finalDownloadLink" class="btn-sm" style="background:var(--surface);color:var(--text);border:1px solid var(--border);text-decoration:none;padding:3px 8px;border-radius:3px;font-size:11px" download>⬇ Download</a>
          <span id="finalPath" style="font-size:10px;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
        </div>
      </div>
    </div>
  </div>

</div>

<!-- Config panel -->
<div class="config-panel">
  <div class="config-toggle open" id="configToggle" onclick="toggleConfig()">
    ⚙ Config <span class="arrow">▲</span>
  </div>
  <div class="config-body open" id="configBody">
    <div class="cfg-grid">
      <div class="cfg-field">
        <span class="cfg-label">TTS Engine</span>
        <select id="cfgTts">
          <option value="kokoro">kokoro</option>
          <option value="qwen3">qwen3</option>
        </select>
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Narration Language</span>
        <select id="cfgLang">
          <option value="en">English (en)</option>
          <option value="fr">French (fr)</option>
          <option value="es">Spanish (es)</option>
          <option value="de">German (de)</option>
          <option value="it">Italian (it)</option>
          <option value="pt">Portuguese (pt)</option>
          <option value="nl">Dutch (nl)</option>
          <option value="ja">Japanese (ja)</option>
          <option value="zh">Chinese (zh)</option>
        </select>
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Image Engine</span>
        <select id="cfgImgEngine">
          <option value="flux2cloud">flux2cloud</option>
          <option value="flux2">flux2 (local)</option>
        </select>
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Image Size</span>
        <select id="cfgImgSize">
          <option value="landscape">landscape (1024×768)</option>
          <option value="square">square (1024×1024)</option>
          <option value="portrait">portrait (768×1024)</option>
          <option value="youtube">youtube (1280×720)</option>
          <option value="wide">wide (1024×576)</option>
        </select>
      </div>
      <div class="cfg-field">
        <span class="cfg-label">FPS</span>
        <input type="number" id="cfgFps" min="12" max="60" value="24" style="width:80px" />
      </div>
      <div class="cfg-field" style="grid-column:span 2">
        <span class="cfg-label">Image Style</span>
        <textarea id="cfgImgStyle" rows="2"></textarea>
      </div>
      <div class="cfg-field" style="grid-column:span 2">
        <span class="cfg-label">Narrative Style</span>
        <textarea id="cfgNarrStyle" rows="2"></textarea>
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Ken Burns Zoom From</span>
        <input type="number" id="cfgZoomFrom" min="0.5" max="2.0" step="0.05" value="1.0" />
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Ken Burns Zoom To</span>
        <input type="number" id="cfgZoomTo" min="0.5" max="2.0" step="0.05" value="1.3" />
      </div>
      <div class="cfg-field" style="grid-column:span 2">
        <span class="cfg-label">Ken Burns Motion</span>
        <select id="cfgMotion">
          <option value="random">random (variety per clip)</option>
          <option value="zoom_in">zoom in — centre</option>
          <option value="zoom_out">zoom out — centre</option>
          <option value="zoom_in_random">zoom in → random point</option>
          <option value="zoom_out_random">zoom out ← random point</option>
          <option value="zoom_random">zoom random (in or out, random point)</option>
          <option value="zoom_in_tl">zoom in → top-left</option>
          <option value="zoom_in_tr">zoom in → top-right</option>
          <option value="zoom_in_bl">zoom in → bottom-left</option>
          <option value="zoom_in_br">zoom in → bottom-right</option>
          <option value="pan_right">pan right</option>
          <option value="pan_left">pan left</option>
          <option value="pan_up">pan up</option>
          <option value="pan_down">pan down</option>
          <option value="drift_tl">drift top-left</option>
          <option value="drift_tr">drift top-right</option>
        </select>
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Chapter Transition</span>
        <select id="cfgTransition">
          <option value="none">none (silence only)</option>
          <option value="fade">fade to black</option>
          <option value="crossfade">crossfade / dissolve</option>
          <option value="random">random (chosen at render)</option>
        </select>
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Transition / Silence (s)</span>
        <input type="number" id="cfgTransitionDuration" min="0" max="10" step="0.1" value="1.0" style="width:80px" />
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Image Seed</span>
        <input type="number" id="cfgImgSeed" placeholder="random" min="0" style="width:120px" />
      </div>
      <div class="cfg-field">
        <span class="cfg-label">Image Steps</span>
        <input type="number" id="cfgImgSteps" placeholder="default" min="1" max="150" style="width:100px" />
      </div>
      <div class="cfg-field" style="grid-column:span 2">
        <label style="display:flex;align-items:center;gap:10px;cursor:pointer">
          <input type="checkbox" id="cfgDraftMode" />
          <span>Draft Mode</span>
          <span style="color:var(--text-dim);font-size:11px">(512×288 images, 1 step — fastest draft preview)</span>
        </label>
      </div>
    </div>
    <div class="cfg-prompts">
      <div style="margin-bottom:8px;padding:8px;background:var(--bg3);border-radius:4px;border:1px solid var(--border)">
        <div style="font-size:11px;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Prompt Parameters <span style="font-weight:400;text-transform:none;color:var(--accent);font-size:10px">— available as placeholders in prompts below</span></div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px">
          <div class="cfg-field">
            <span class="cfg-label">Chapter Range</span>
            <input type="text" id="cfgChapterRange" placeholder="2–5" />
            <span style="font-size:10px;color:var(--text-dim)">{chapter_range}</span>
          </div>
          <div class="cfg-field">
            <span class="cfg-label">Scenes per Chapter</span>
            <input type="text" id="cfgSceneRange" placeholder="2–5" />
            <span style="font-size:10px;color:var(--text-dim)">{scene_range}</span>
          </div>
          <div class="cfg-field">
            <span class="cfg-label">Scene Duration</span>
            <input type="text" id="cfgSceneDuration" placeholder="15–45 seconds" />
            <span style="font-size:10px;color:var(--text-dim)">{scene_duration}</span>
          </div>
        </div>
        <div style="margin-top:6px;font-size:10px;color:var(--text-dim)">Also available: <code style="color:var(--accent)">{lang}</code> <code style="color:var(--accent)">{narrative_style}</code> <code style="color:var(--accent)">{image_style}</code></div>
      </div>
      <div class="prompt-field">
        <div class="prompt-label">Story Breakdown Prompt <span class="prompt-info" id="infoStory" data-content="">ⓘ</span></div>
        <select id="cfgPromptStorySel" class="prompt-sel" onchange="onPromptSelect('Story')"></select>
        <textarea class="prompt-area" id="cfgPromptStory" rows="4" placeholder="Optional inline override — leave empty to use the selected prompt"></textarea>
      </div>
      <div class="prompt-field">
        <div class="prompt-label">Scene Transcript Prompt <span class="prompt-info" id="infoTranscript" data-content="">ⓘ</span></div>
        <select id="cfgPromptTranscriptSel" class="prompt-sel" onchange="onPromptSelect('Transcript')"></select>
        <textarea class="prompt-area" id="cfgPromptTranscript" rows="4" placeholder="Optional inline override — leave empty to use the selected prompt"></textarea>
      </div>
      <div class="prompt-field">
        <div class="prompt-label">Scene Image Prompt <span class="prompt-info" id="infoImage" data-content="">ⓘ</span></div>
        <select id="cfgPromptImageSel" class="prompt-sel" onchange="onPromptSelect('Image')"></select>
        <textarea class="prompt-area" id="cfgPromptImage" rows="4" placeholder="Optional inline override — leave empty to use the selected prompt"></textarea>
      </div>
    </div>
    <div style="margin-top:12px;display:flex;gap:8px;">
      <button class="btn btn-primary" onclick="saveConfig()">Save Config</button>
      <span id="cfgSaveMsg" style="font-size:11px;color:var(--green);align-self:center;"></span>
    </div>
  </div>
</div>

<script>
const STEP_LABELS = {
  gen_transcript: 'Transcript', gen_image_prompt: 'Img Prompt',
  gen_audio: 'Audio', gen_image: 'Image', assemble_clip: 'Clip'
};
const GLOBAL_STEP_LABELS = {
  parse: 'Parse Script', transcript: 'Transcripts', image_prompt: 'Image Prompts',
  audio: 'Audio', image: 'Images', clip: 'Clips',
  chapter: 'Ch. Merges', final: 'Final Video'
};
const GLOBAL_STEP_ORDER = ['parse','transcript','image_prompt','audio','image','clip','chapter','final'];

let state = null;
let selectedSceneId = null;
let pollTimer = null;
let configOpen = true;
let _consoleClear = 0;
let _waitingForInit = false;
let _lastRenderedSceneJson = null;  // last scene data that was rendered in detail panel
let _pendingDetailUpdate = false;   // data changed while panel was busy — flush when free
let _lastFormatJson = null;
let _pendingFormatUpdate = false;
let _lastMatrixJson = null;
let _pendingMatrixUpdate = false;
let viewMode = localStorage.getItem('sb-view-mode') || 'chapter';
let formatTab = localStorage.getItem('sb-format-tab') || 'transcript';

// ── Bootstrap ──────────────────────────────────────────────────────────────────
async function boot() {
  restorePanels();
  setViewMode(viewMode);
  setFormatTab(formatTab);
  await loadConfig();
  await pollJob();
}

async function loadConfig() {
  try {
    const r = await fetch('/api/storyboard/config');
    if (!r.ok) return;
    const cfg = await r.json();
    document.getElementById('cfgTts').value = cfg.tts_engine || 'kokoro';
    document.getElementById('cfgLang').value = cfg.language || 'en';
    document.getElementById('cfgImgEngine').value = cfg.image_engine || 'flux2cloud';
    document.getElementById('cfgImgSize').value = cfg.image_size || 'landscape';
    document.getElementById('cfgImgStyle').value = cfg.image_style || '';
    document.getElementById('cfgNarrStyle').value = cfg.narrative_style || '';
    document.getElementById('cfgFps').value = cfg.fps || 24;
    document.getElementById('cfgZoomFrom').value = cfg.ken_burns_zoom_from ?? 1.0;
    document.getElementById('cfgZoomTo').value = cfg.ken_burns_zoom_to ?? 1.3;
    document.getElementById('cfgMotion').value = cfg.ken_burns_motion || 'random';
    document.getElementById('cfgTransition').value = cfg.chapter_transition || 'none';
    document.getElementById('cfgTransitionDuration').value = cfg.chapter_transition_duration ?? 1.0;
    document.getElementById('cfgImgSeed').value = cfg.image_seed != null ? cfg.image_seed : '';
    document.getElementById('cfgImgSteps').value = cfg.image_steps != null ? cfg.image_steps : '';
    document.getElementById('cfgDraftMode').checked = cfg.draft_mode || false;
    document.getElementById('cfgChapterRange').value = cfg.chapter_range || '2–5';
    document.getElementById('cfgSceneRange').value = cfg.scene_range || '2–5';
    document.getElementById('cfgSceneDuration').value = cfg.scene_duration || '15–45 seconds';
    const p = cfg.prompts || {};
    const ov = cfg.prompt_overrides || {};
    await populateStoryPrompts();
    document.getElementById('cfgPromptStorySel').value = p.story_breakdown || 'storyboard-breakdown';
    document.getElementById('cfgPromptTranscriptSel').value = p.scene_transcript || 'storyboard-scene-transcript';
    document.getElementById('cfgPromptImageSel').value = p.scene_image_prompt || 'storyboard-scene-image';
    document.getElementById('cfgPromptStory').value = ov.story_breakdown || '';
    document.getElementById('cfgPromptTranscript').value = ov.scene_transcript || '';
    document.getElementById('cfgPromptImage').value = ov.scene_image_prompt || '';
    refreshPromptPreview('Story');
    refreshPromptPreview('Transcript');
    refreshPromptPreview('Image');
  } catch(e) { console.warn('loadConfig error', e); }
}

const _storyPromptCache = {};

async function populateStoryPrompts() {
  try {
    const r = await fetch('/api/storyboard/list-prompts');
    if (!r.ok) return;
    const data = await r.json();
    const names = data.prompts || [];
    for (const key of ['Story', 'Transcript', 'Image']) {
      const sel = document.getElementById('cfgPrompt' + key + 'Sel');
      if (!sel) continue;
      const cur = sel.value;
      sel.innerHTML = '';
      for (const n of names) {
        const o = document.createElement('option');
        o.value = n; o.textContent = n;
        sel.appendChild(o);
      }
      if (names.includes(cur)) sel.value = cur;
    }
  } catch (e) { /* list-prompts unavailable */ }
}

async function refreshPromptPreview(key) {
  const sel = document.getElementById('cfgPrompt' + key + 'Sel');
  const info = document.getElementById('info' + key);
  if (!sel || !info) return;
  const name = sel.value;
  if (!name) { info.setAttribute('data-content', ''); return; }
  if (!_storyPromptCache[name]) {
    try {
      const r = await fetch('/api/storyboard/prompt-content?name=' + encodeURIComponent(name));
      const d = await r.json();
      _storyPromptCache[name] = d.content || '';
    } catch (e) { _storyPromptCache[name] = ''; }
  }
  info.setAttribute('data-content', _storyPromptCache[name]);
}

function onPromptSelect(key) {
  refreshPromptPreview(key);
}

async function saveConfig() {
  const body = {
    tts_engine: document.getElementById('cfgTts').value,
    language: document.getElementById('cfgLang').value,
    image_engine: document.getElementById('cfgImgEngine').value,
    image_size: document.getElementById('cfgImgSize').value,
    image_style: document.getElementById('cfgImgStyle').value,
    narrative_style: document.getElementById('cfgNarrStyle').value,
    fps: parseInt(document.getElementById('cfgFps').value) || 24,
    ken_burns_zoom_from: parseFloat(document.getElementById('cfgZoomFrom').value) || 1.0,
    ken_burns_zoom_to: parseFloat(document.getElementById('cfgZoomTo').value) || 1.3,
    ken_burns_motion: document.getElementById('cfgMotion').value,
    chapter_transition: document.getElementById('cfgTransition').value,
    chapter_transition_duration: parseFloat(document.getElementById('cfgTransitionDuration').value) || 1.0,
    image_seed: document.getElementById('cfgImgSeed').value !== '' ? parseInt(document.getElementById('cfgImgSeed').value) : null,
    image_steps: document.getElementById('cfgImgSteps').value !== '' ? parseInt(document.getElementById('cfgImgSteps').value) : null,
    draft_mode: document.getElementById('cfgDraftMode').checked,
    chapter_range: document.getElementById('cfgChapterRange').value || '2–5',
    scene_range: document.getElementById('cfgSceneRange').value || '2–5',
    scene_duration: document.getElementById('cfgSceneDuration').value || '15–45 seconds',
    prompts: {
      story_breakdown: document.getElementById('cfgPromptStorySel').value,
      scene_transcript: document.getElementById('cfgPromptTranscriptSel').value,
      scene_image_prompt: document.getElementById('cfgPromptImageSel').value,
    },
    prompt_overrides: {
      story_breakdown: document.getElementById('cfgPromptStory').value,
      scene_transcript: document.getElementById('cfgPromptTranscript').value,
      scene_image_prompt: document.getElementById('cfgPromptImage').value,
    }
  };
  try {
    const r = await fetch('/api/storyboard/config', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const msg = document.getElementById('cfgSaveMsg');
    if (r.ok) { msg.textContent = '✓ Saved'; setTimeout(() => msg.textContent = '', 2000); }
    else { msg.textContent = 'Error saving'; msg.style.color = 'var(--red)'; }
  } catch(e) { console.error(e); }
}

// ── Project init ──────────────────────────────────────────────────────────────
async function initProject() {
  const text = document.getElementById('initScriptText').value.trim();
  if (!text) { document.getElementById('initError').textContent = 'Please paste your script text above'; return; }
  try {
    const r = await fetch('/api/storyboard/init', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({script_text: text}) });
    if (!r.ok) { const e = await r.json(); document.getElementById('initError').textContent = e.detail || 'Error'; return; }
    const data = await r.json();
    _waitingForInit = false;
    document.getElementById('initOverlay').style.display = 'none';
    applyState(data);
    schedulePoll();
  } catch(e) { document.getElementById('initError').textContent = String(e); }
}

function resetProject() {
  state = null;
  selectedSceneId = null;
  _waitingForInit = true;
  clearTimeout(pollTimer); // stop polling so old state doesn't re-hide the overlay
  document.getElementById('initOverlay').style.display = 'flex';
  document.getElementById('initScriptText').value = '';
  document.getElementById('initError').textContent = '';
  document.getElementById('errorBanner').className = 'error-banner';
}

// ── View mode ────────────────────────────────────────────────────────────────
function setViewMode(mode) {
  viewMode = mode;
  localStorage.setItem('sb-view-mode', mode);
  const isChapter = mode === 'chapter';
  const isFormat  = mode === 'format';
  const isMatrix  = mode === 'matrix';
  ['treePanel','detailPanel','consolePanel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = isChapter ? '' : 'none';
  });
  document.getElementById('formatPanel').classList.toggle('visible', isFormat);
  document.getElementById('matrixPanel').classList.toggle('visible', isMatrix);
  document.getElementById('vtabChapter').classList.toggle('active', isChapter);
  document.getElementById('vtabFormat').classList.toggle('active', isFormat);
  document.getElementById('vtabMatrix').classList.toggle('active', isMatrix);
  if (isFormat && state) renderFormatView(state.chapters || []);
  if (isMatrix && state) renderMatrixView(state.chapters || []);
}

function setFormatTab(tab) {
  formatTab = tab;
  localStorage.setItem('sb-format-tab', tab);
  ['transcript','audio','image','clip'].forEach(t => {
    const el = document.getElementById('ftab' + t.charAt(0).toUpperCase() + t.slice(1));
    if (el) el.classList.toggle('active', t === tab);
  });
  if (state) renderFormatView(state.chapters || []);
}

function _formatIsBusy() {
  const fp = document.getElementById('formatPanel');
  if (!fp) return false;
  const active = document.activeElement;
  if (active && fp.contains(active) && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT')) return true;
  return [...fp.querySelectorAll('audio,video')].some(m => !m.paused);
}

function _matrixIsBusy() {
  const mp = document.getElementById('matrixPanel');
  if (!mp) return false;
  return [...mp.querySelectorAll('audio,video')].some(m => !m.paused);
}

function renderFormatView(chapters) {
  const body = document.getElementById('formatBody');
  if (!body) return;
  const canEdit = state && !state.running;
  const blocks = [];
  for (const ch of chapters) {
    for (const sc of (ch.scenes || [])) {
      let inner = '';
      if (formatTab === 'transcript') {
        inner = `<textarea class="edit-area" id="fmtTx_${sc.id}" ${canEdit ? '' : 'readonly'}>${esc(sc.transcript || '')}</textarea>
          ${canEdit ? `<div><button class="btn-sm btn-primary" onclick="saveTranscript('${sc.id}')">Save</button></div>` : ''}`;
      } else if (formatTab === 'audio') {
        inner = sc.audio_file
          ? `<audio class="fmt-audio" controls src="/api/storyboard/preview?file=${encodeURIComponent(sc.audio_file)}"></audio>`
          : `<span style="color:var(--text-dim);font-size:11px">Not yet generated</span>`;
      } else if (formatTab === 'image') {
        inner = sc.image_file
          ? `<img class="fmt-img" src="/api/storyboard/preview?file=${encodeURIComponent(sc.image_file)}" onclick="window.open(this.src)" />`
          : `<span style="color:var(--text-dim);font-size:11px">Not yet generated</span>`;
      } else if (formatTab === 'clip') {
        inner = sc.clip_file
          ? `<video class="fmt-vid" controls src="/api/storyboard/preview?file=${encodeURIComponent(sc.clip_file)}"></video>`
          : `<span style="color:var(--text-dim);font-size:11px">Not yet generated</span>`;
      }
      blocks.push(`<div class="format-scene-block">
        <div class="format-scene-chapter">${esc(ch.title || ch.id)}</div>
        <div class="format-scene-title">${esc(sc.title || sc.id)}</div>
        ${inner}
      </div>`);
    }
  }
  body.innerHTML = blocks.length ? blocks.join('') : '<div class="no-state">No scenes yet.</div>';
}

function renderMatrixView(chapters) {
  const wrap = document.getElementById('matrixTable');
  if (!wrap) return;
  const stepOrder = ['gen_transcript','gen_image_prompt','gen_audio','gen_image','assemble_clip'];
  const rows = [];
  for (const ch of chapters) {
    for (const sc of (ch.scenes || [])) {
      const dots = stepOrder.map(k => {
        const st = (sc.steps && sc.steps[k]) ? sc.steps[k].status : 'pending';
        return `<span class="dot ${st === 'done' ? 'done' : st === 'running' ? 'running' : st === 'error' ? 'error' : st === 'skipped' ? 'skipped' : ''}" title="${STEP_LABELS[k]||k}: ${st}"></span>`;
      }).join('');
      const imgCell = sc.image_file
        ? `<img class="matrix-img" src="/api/storyboard/preview?file=${encodeURIComponent(sc.image_file)}" onclick="window.open(this.src)" loading="lazy" />`
        : `<span class="matrix-empty">—</span>`;
      const audioCell = sc.audio_file
        ? `<audio class="matrix-audio" controls src="/api/storyboard/preview?file=${encodeURIComponent(sc.audio_file)}"></audio>`
        : `<span class="matrix-empty">—</span>`;
      const videoCell = sc.clip_file
        ? `<video class="matrix-video" controls src="/api/storyboard/preview?file=${encodeURIComponent(sc.clip_file)}"></video>`
        : `<span class="matrix-empty">—</span>`;
      const textCell = sc.transcript
        ? `<div class="matrix-full-text">${esc(sc.transcript)}</div>`
        : `<span class="matrix-empty">Not yet generated</span>`;
      rows.push(`<tr>
        <td class="matrix-col-scene">
          <div class="matrix-scene-chapter">${esc(ch.title || ch.id)}</div>
          <div class="matrix-scene-title" onclick="setViewMode('chapter');selectScene('${sc.id}','${ch.id}')">${esc(sc.title || sc.id)}</div>
          <div class="matrix-scene-dots">${dots}</div>
        </td>
        <td>${textCell}</td>
        <td class="matrix-col-image">${imgCell}</td>
        <td class="matrix-col-audio">${audioCell}</td>
        <td class="matrix-col-video">${videoCell}</td>
      </tr>`);
    }
  }
  if (!rows.length) {
    wrap.innerHTML = '<div class="no-state">No scenes yet.</div>';
    return;
  }
  wrap.innerHTML = `<table class="matrix-tbl">
    <thead><tr>
      <th class="matrix-col-scene">Scene</th>
      <th>Text</th>
      <th class="matrix-col-image">Image</th>
      <th class="matrix-col-audio">Audio</th>
      <th class="matrix-col-video">Video</th>
    </tr></thead>
    <tbody>${rows.join('')}</tbody>
  </table>`;
}

// ── Polling ───────────────────────────────────────────────────────────────────
async function pollJob() {
  try {
    const r = await fetch('/api/storyboard/job');
    if (!r.ok) { schedulePoll(); return; }
    const data = await r.json();
    applyState(data);
    if (data.running) schedulePoll();
    else if (data.initialized) schedulePoll(5000);
  } catch(e) { schedulePoll(3000); }
}

function schedulePoll(ms = 1500) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(pollJob, ms);
}

// ── State rendering ───────────────────────────────────────────────────────────
function applyState(data) {
  if (!data.initialized || _waitingForInit) {
    document.getElementById('initOverlay').style.display = 'flex';
    document.getElementById('btnRunAll').disabled = true;
    ['btnRegenAudio','btnRegenImage','btnRegenClip','btnRegenFinal'].forEach(id => document.getElementById(id).disabled = true);
    document.getElementById('btnStop').disabled = true;
    document.getElementById('btnScript').disabled = true;
    return;
  }
  document.getElementById('initOverlay').style.display = 'none';
  state = data;

  // Workdir label
  const wd = data.workdir || '';
  document.getElementById('workdirLabel').textContent = wd.split('/').slice(-2).join('/') || wd;

  // Status badge
  const overall = overallStatus(data);
  const badge = document.getElementById('statusBadge');
  badge.textContent = data.running ? 'running' : overall;
  badge.className = 'status-badge s-' + (data.running ? 'running' : overall);

  // Buttons
  const hasScenes = data.chapters && data.chapters.some(ch => ch.scenes && ch.scenes.length > 0);
  const allDone = overall === 'done';
  const hasAnyDone = overall !== 'idle';
  const btnRun = document.getElementById('btnRunAll');
  btnRun.disabled = data.running || allDone;
  btnRun.textContent = hasAnyDone ? '▶ Run Remaining' : '▶ Run All';
  ['btnRegenAudio','btnRegenImage','btnRegenClip','btnRegenFinal'].forEach(id => document.getElementById(id).disabled = data.running || !hasScenes);
  document.getElementById('btnStop').disabled = !data.running;
  document.getElementById('btnScript').disabled = false;

  // Error banner
  updateErrorBanner(data);
  renderFinalPanel(data);

  // Global steps sidebar
  renderGlobalSteps(data.global_steps || {});

  // Scene tree
  renderTree(data.chapters || []);

  // Format / matrix views: skip re-render when data is unchanged or media is playing
  const _chapJson = JSON.stringify(data.chapters || []);
  if (viewMode === 'format') {
    if (_chapJson !== _lastFormatJson) _pendingFormatUpdate = true;
    if (_pendingFormatUpdate && !_formatIsBusy()) {
      _lastFormatJson = _chapJson; _pendingFormatUpdate = false;
      renderFormatView(data.chapters || []);
    }
  }
  if (viewMode === 'matrix') {
    if (_chapJson !== _lastMatrixJson) _pendingMatrixUpdate = true;
    if (_pendingMatrixUpdate && !_matrixIsBusy()) {
      _lastMatrixJson = _chapJson; _pendingMatrixUpdate = false;
      renderMatrixView(data.chapters || []);
    }
  }

  // Console
  renderConsole(data.console_log || []);

  // Detail panel — only re-render when data changed, and never while the panel is busy
  if (selectedSceneId) {
    const sc = findScene(data.chapters || [], selectedSceneId);
    if (sc) {
      const scJson = JSON.stringify(sc);
      if (scJson !== _lastRenderedSceneJson) _pendingDetailUpdate = true;
      if (_pendingDetailUpdate && !_detailIsBusy()) {
        _lastRenderedSceneJson = scJson;
        _pendingDetailUpdate = false;
        renderDetail(sc, findChapterForScene(data.chapters || [], selectedSceneId));
      }
    }
  }
}

function _detailIsBusy() {
  const detail = document.getElementById('detailPanel');
  if (!detail) return false;
  // Typing / focus in a form element
  const active = document.activeElement;
  if (active && detail.contains(active) &&
      (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT')) return true;
  // Audio or video is playing
  return [...detail.querySelectorAll('audio,video')].some(m => !m.paused);
}

function overallStatus(data) {
  const gs = data.global_steps || {};
  const vals = Object.values(gs);
  if (vals.includes('running')) return 'running';
  if (vals.includes('error')) return 'error';
  if (vals.every(s => s === 'done')) return 'done';
  if (vals.some(s => s === 'done' || s === 'partial')) return 'partial';
  return 'idle';
}

function stepIcon(status) {
  return {pending:'⏳', running:'▶', done:'✅', error:'❌', skipped:'⏭', partial:'◑'}[status] || '⏳';
}

function renderGlobalSteps(gsteps) {
  const el = document.getElementById('globalSteps');
  const canRun = state && !state.running;
  el.innerHTML = GLOBAL_STEP_ORDER.map(k => {
    const st = gsteps[k] || 'pending';
    const btns = canRun ? `<div class="gstep-actions">
      <button class="gstep-btn" onclick="event.stopPropagation();runOnly('${k}')" title="Run only this step">1</button>
      <button class="gstep-btn" onclick="event.stopPropagation();runFromGlobal('${k}')" title="Run from this step">▶▶</button>
    </div>` : '';
    return `<div class="gstep">
      <span class="gstep-icon">${stepIcon(st)}</span>
      <span class="gstep-name">${GLOBAL_STEP_LABELS[k]}</span>
      ${btns}
    </div>`;
  }).join('');
}

function fmtDur(secs) {
  if (!secs || secs <= 0) return '';
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function computeStats(chapters) {
  let words = 0, durTotal = 0;
  const chDurs = {};
  for (const ch of chapters) {
    let chDur = 0;
    for (const sc of ch.scenes || []) {
      if (sc.transcript) words += sc.transcript.trim().split(/\s+/).filter(Boolean).length;
      if (sc.audio_duration) { chDur += sc.audio_duration; durTotal += sc.audio_duration; }
    }
    chDurs[ch.id] = chDur;
  }
  return { words, durTotal, chDurs };
}

function renderTree(chapters) {
  const body = document.getElementById('treeBody');
  const statsBar = document.getElementById('statsBar');
  if (!chapters.length) {
    body.innerHTML = '<div class="no-state">No chapters yet. Click ▶ Run All to parse the script.</div>';
    if (statsBar) statsBar.textContent = '';
    return;
  }
  const { words, durTotal, chDurs } = computeStats(chapters);
  if (statsBar) {
    const parts = [];
    if (words > 0) parts.push(`<b>${words.toLocaleString()}</b> words`);
    if (durTotal > 0) parts.push(`<b>${fmtDur(durTotal)}</b> total audio`);
    statsBar.innerHTML = parts.join(' · ');
  }
  body.innerHTML = chapters.map((ch, ci) => {
    const chSt = ch.merge_step ? ch.merge_step.status : 'pending';
    const chDur = chDurs[ch.id] || 0;
    const chDurBadge = chDur > 0 ? `<span class="dur-badge">${fmtDur(chDur)}</span>` : '';
    const scenesHtml = (ch.scenes || []).map(sc => {
      const dots = Object.entries(sc.steps || {}).map(([k, s]) =>
        `<div class="dot ${s.status}" title="${k}: ${s.status}"></div>`).join('');
      const sel = sc.id === selectedSceneId ? ' selected' : '';
      const durBadge = sc.audio_duration ? `<span class="dur-badge">${fmtDur(sc.audio_duration)}</span>` : '';
      return `<div class="scene-row${sel}" onclick="selectScene('${sc.id}','${ch.id}')">
        <span class="scene-title">${sc.title || sc.id}</span>
        ${durBadge}
        <div class="step-dots">${dots}</div>
      </div>`;
    }).join('');
    return `<div class="chapter-node">
      <div class="chapter-header" onclick="toggleChapter(this)">
        <span class="chapter-toggle">▾</span>
        <span class="chapter-title">${ch.title || ch.id}</span>
        ${chDurBadge}
        <span class="chapter-status">${stepIcon(chSt)}</span>
        ${ch.chapter_file ? `<button class="btn-sm btn-neutral" onclick="event.stopPropagation();previewFile('${ch.chapter_file}','video')">▶</button>` : ''}
      </div>
      <div class="scene-list">${scenesHtml}</div>
    </div>`;
  }).join('');
}

function toggleChapter(el) {
  const list = el.nextElementSibling;
  const arrow = el.querySelector('.chapter-toggle');
  if (list.style.display === 'none') { list.style.display = ''; arrow.textContent = '▾'; }
  else { list.style.display = 'none'; arrow.textContent = '▸'; }
}

function selectScene(sceneId, chapterId) {
  selectedSceneId = sceneId;
  _lastRenderedSceneJson = null;  // force re-render for the newly selected scene
  _pendingDetailUpdate = false;
  if (state) renderTree(state.chapters || []);
  const ch = findChapterForScene(state ? state.chapters : [], sceneId);
  const sc = findScene(state ? state.chapters : [], sceneId);
  if (sc) { _lastRenderedSceneJson = JSON.stringify(sc); renderDetail(sc, ch); }
}

function togglePanel(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const collapsed = el.classList.toggle('panel-collapsed');
  // update the ▾/▸ arrow inside this panel's header
  const toggle = el.querySelector('.ph-toggle');
  if (toggle) toggle.textContent = collapsed ? '▸' : '▾';
  try { localStorage.setItem('sb-panel-' + id, collapsed ? '1' : '0'); } catch(e) {}
}

function restorePanels() {
  ['treePanel','detailPanel','consolePanel','finalPanel'].forEach(id => {
    try {
      if (localStorage.getItem('sb-panel-' + id) === '1') {
        const el = document.getElementById(id);
        if (el) { el.classList.add('panel-collapsed'); const t = el.querySelector('.ph-toggle'); if (t) t.textContent = '▸'; }
      }
    } catch(e) {}
  });
}

function renderDetail(sc, ch) {
  const panel = document.getElementById('detailBody');
  const stepsHtml = Object.entries(sc.steps || {}).map(([k, s]) => {
    const elapsed = s.elapsed_seconds != null ? ` (${s.elapsed_seconds}s)` : '';
    const rerunBtn = state && !state.running
      ? `<button class="btn-sm btn-neutral step-rerun" onclick="rerunStep('${sc.id}','${k}')">re-run</button>`
      : '';
    const outFile = s.output_file ? `<a href="/api/storyboard/download?file=${encodeURIComponent(s.output_file)}" download style="font-size:10px;color:var(--accent)">⬇</a>` : '';
    const log = s.output ? `<div class="step-card-log">${esc(s.output.slice(-500))}</div>` : '';
    return `<div class="step-card">
      <div class="step-card-header">
        <span>${stepIcon(s.status)}</span>
        <span class="step-card-name">${STEP_LABELS[k]||k}${elapsed}</span>
        ${outFile}${rerunBtn}
      </div>
      ${log}
    </div>`;
  }).join('');

  const audioHtml = sc.audio_file
    ? `<div><div class="detail-label">Audio</div><audio controls src="/api/storyboard/preview?file=${encodeURIComponent(sc.audio_file)}"></audio></div>`
    : '';
  const imageHtml = sc.image_file
    ? `<div><div class="detail-label">Image</div><img class="scene-img" src="/api/storyboard/preview?file=${encodeURIComponent(sc.image_file)}" onclick="window.open(this.src)" /></div>`
    : '';
  const videoHtml = sc.clip_file
    ? `<div><div class="detail-label">Clip</div><video class="scene-vid" controls src="/api/storyboard/preview?file=${encodeURIComponent(sc.clip_file)}"></video></div>`
    : '';

  const canEdit = state && !state.running;
  const rerunSceneBtn = canEdit
    ? `<div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn btn-neutral btn-sm" onclick="rerunScene('${sc.id}','gen_transcript')">Re-run from Transcript</button>
        <button class="btn btn-neutral btn-sm" onclick="rerunScene('${sc.id}','gen_audio')">Re-run from Audio</button>
        <button class="btn btn-neutral btn-sm" onclick="rerunScene('${sc.id}','gen_image')">Re-run from Image</button>
        <button class="btn btn-neutral btn-sm" onclick="rerunScene('${sc.id}','assemble_clip')">Re-run Clip only</button>
        <button class="btn btn-primary btn-sm" onclick="testOneImage('${sc.id}')" title="Generate only this scene's image (test mode)">🧪 Test 1 Image</button>
      </div>`
    : '';

  panel.innerHTML = `
    <div class="detail-title">${esc(sc.title || sc.id)}</div>
    ${rerunSceneBtn}
    <div>
      <div class="detail-label">Description</div>
      <div style="font-size:12px;color:var(--text-muted);line-height:1.5">${esc(sc.raw_description)}</div>
    </div>
    <div>
      <div class="detail-label" style="margin-bottom:4px">Transcript
        ${canEdit ? `<button class="btn-sm btn-primary" onclick="saveTranscript('${sc.id}')" style="margin-left:6px">Save</button>` : ''}
      </div>
      <textarea class="edit-area" id="txTranscript_${sc.id}" ${canEdit ? '' : 'readonly'}>${esc(sc.transcript || '')}</textarea>
    </div>
    <div>
      <div class="detail-label" style="margin-bottom:4px">Image Prompt
        ${canEdit ? `<button class="btn-sm btn-primary" onclick="saveImagePrompt('${sc.id}')" style="margin-left:6px">Save</button>` : ''}
      </div>
      <textarea class="edit-area" id="txImagePrompt_${sc.id}" ${canEdit ? '' : 'readonly'}>${esc(sc.image_prompt || '')}</textarea>
    </div>
    <div class="media-row">${audioHtml}${imageHtml}${videoHtml}</div>
    <div>
      <div class="detail-label" style="margin-bottom:6px">Step Status</div>
      <div class="step-grid">${stepsHtml}</div>
    </div>`;
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function runAll() {
  await postRun({});
}

async function runOnly(step) {
  if (state && state.running) return;
  if (step === 'parse' && state && state.chapters && state.chapters.length > 0) {
    if (!confirm('Re-running "Parse Script" will DELETE all generated chapters, scenes, audio, images, clips, and the final video.\n\nContinue?')) return;
  }
  await postRun({ only_global_step: step });
}

async function runFromGlobal(step) {
  if (state && state.running) return;
  if (step === 'parse' && state && state.chapters && state.chapters.length > 0) {
    if (!confirm('Re-running from "Parse Script" will DELETE all generated chapters, scenes, audio, images, clips, and the final video.\n\nContinue?')) return;
  } else {
    if (!confirm(`Re-run pipeline from step "${GLOBAL_STEP_LABELS[step]}"?`)) return;
  }
  await postRun({ from_global_step: step });
}

async function rerunStep(sceneId, stepName) {
  await postRun({ scene_id: sceneId, from_step: stepName, only_step: true });
}

async function rerunScene(sceneId, fromStep) {
  await postRun({ scene_id: sceneId, from_step: fromStep, only_scene: true });
}

async function testOneImage(sceneId) {
  await postRun({ scene_id: sceneId, from_step: 'gen_image', only_step: true });
}

async function regenStep(step) {
  if (state && state.running) return;
  await postRun({ only_global_step: step });
}

async function regenMerge() {
  if (state && state.running) return;
  await postRun({ from_global_step: 'chapter' });
}

function renderFinalPanel(data) {
  const panel = document.getElementById('finalPanel');
  const video = document.getElementById('finalVideo');
  const dl    = document.getElementById('finalDownloadLink');
  const badge = document.getElementById('finalStatus');
  const path  = document.getElementById('finalPath');
  const finalFile = data && data.final_file;
  // Use end_time as cache-buster: when the file is regenerated, end_time changes
  // → new URL → browser re-fetches even if the path is identical.
  const finalEnd = (data && data.final_step && data.final_step.end_time) || 0;
  if (finalFile) {
    const cacheKey = finalFile + '|' + finalEnd;
    const url = '/api/storyboard/preview?file=' + encodeURIComponent(finalFile)
              + (finalEnd ? '&t=' + Math.floor(finalEnd) : '');
    if (video.dataset.src !== cacheKey) {
      video.dataset.src = cacheKey;
      video.src = url;
      dl.href = '/api/storyboard/download?file=' + encodeURIComponent(finalFile);
      dl.download = finalFile.split('/').pop();
      path.textContent = finalFile.split('/').slice(-3).join('/');
      badge.textContent = '✓ ready';
    }
    panel.style.display = '';
    if (panel.classList.contains('panel-collapsed') && !video.dataset.src) {
      panel.classList.remove('panel-collapsed');
      const t = panel.querySelector('.ph-toggle'); if (t) t.textContent = '▾';
    }
  } else {
    if (panel.style.display !== 'none') {
      panel.style.display = 'none';
      video.src = '';
      video.dataset.src = '';
    }
  }
}

async function postRun(body) {
  try {
    const r = await fetch('/api/storyboard/run', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    if (r.status === 409) { alert('Pipeline already running'); return; }
    if (!r.ok) { const e = await r.json(); alert(e.detail || 'Error'); return; }
    document.getElementById('btnRunAll').disabled = true;
    ['btnRegenAudio','btnRegenImage','btnRegenClip','btnRegenFinal'].forEach(id => document.getElementById(id).disabled = true);
    document.getElementById('btnStop').disabled = false;
    schedulePoll(500);
  } catch(e) { alert(String(e)); }
}

async function stopPipeline() {
  await fetch('/api/storyboard/stop', { method: 'POST' });
  document.getElementById('btnStop').disabled = true;
  schedulePoll(800);
}

async function saveTranscript(sceneId) {
  const val = document.getElementById('txTranscript_' + sceneId).value;
  await fetch(`/api/storyboard/scene/${sceneId}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ transcript: val }),
  });
}

async function saveImagePrompt(sceneId) {
  const val = document.getElementById('txImagePrompt_' + sceneId).value;
  await fetch(`/api/storyboard/scene/${sceneId}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ image_prompt: val }),
  });
}

function previewFile(path, type) {
  window.open('/api/storyboard/preview?file=' + encodeURIComponent(path));
}

// ── Script modal ─────────────────────────────────────────────────────────────
function showScriptModal() {
  const text = state && state.script_text ? state.script_text : '';
  document.getElementById('scriptModalText').value = text;
  document.getElementById('scriptModal').className = 'modal-overlay open';
}

function closeScriptModal() {
  document.getElementById('scriptModal').className = 'modal-overlay';
}

async function saveScript() {
  const text = document.getElementById('scriptModalText').value.trim();
  if (!text) { alert('Script text is empty'); return; }
  try {
    const r = await fetch('/api/storyboard/script', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ script_text: text }),
    });
    if (!r.ok) { const e = await r.json(); alert(e.detail || 'Error saving script'); return; }
    closeScriptModal();
    schedulePoll(300);
  } catch(e) { alert(String(e)); }
}

// ── Console ───────────────────────────────────────────────────────────────────
function renderConsole(entries) {
  const body = document.getElementById('consoleBody');
  if (!body) return;
  const visible = entries.slice(_consoleClear);
  if (!visible.length) return;
  body.innerHTML = visible.map(e => {
    const t = new Date(e.t * 1000);
    const ts = t.toTimeString().slice(0, 8);
    const ok = e.rc === 0 || e.rc == null;
    const cls = ok ? 'console-ok' : 'console-err';
    const rcBadge = e.rc != null ? ` <span style="color:${ok?'var(--green)':'var(--red)'}">[${e.rc}]</span>` : '';
    const out = e.output ? `<div class="${cls}">${esc(e.output.slice(-800))}</div>` : '';
    return `<div class="console-entry">
      <div><span class="console-ts">[${ts}]</span> <span class="console-cmd">${esc(e.cmd)}</span>${rcBadge}</div>
      ${out}
    </div>`;
  }).join('');
  // Only auto-scroll if user is already near the bottom (within 60px)
  if (body.scrollHeight - body.scrollTop - body.clientHeight < 60) {
    body.scrollTop = body.scrollHeight;
  }
}

function clearConsoleDisplay() {
  const body = document.getElementById('consoleBody');
  if (body) body.innerHTML = '<span style="color:var(--text-dim)">Console cleared (history preserved).</span>';
  if (state && state.console_log) _consoleClear = state.console_log.length;
}

// ── Error banner ──────────────────────────────────────────────────────────────
function updateErrorBanner(data) {
  const gs = data.global_steps || {};
  const hasError = Object.values(gs).some(s => s === 'error');
  document.getElementById('errorBanner').className = 'error-banner' + (hasError ? ' visible' : '');
}

// ── Config toggle ─────────────────────────────────────────────────────────────
function toggleConfig() {
  configOpen = !configOpen;
  document.getElementById('configBody').className = 'config-body' + (configOpen ? ' open' : '');
  document.getElementById('configToggle').className = 'config-toggle' + (configOpen ? ' open' : '');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function findScene(chapters, id) {
  for (const ch of chapters) for (const sc of (ch.scenes||[])) if (sc.id === id) return sc;
  return null;
}
function findChapterForScene(chapters, id) {
  for (const ch of chapters) for (const sc of (ch.scenes||[])) if (sc.id === id) return ch;
  return null;
}
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

boot();
</script>
</body>
</html>"""


def register(config: dict) -> WebuxPluginManifest:
    return WebuxPluginManifest(
        name="storyboard",
        tab_label="Storyboard",
        tab_icon="📽",
        api_router=router,
        frontend_html=_HTML,
        order=60,
        lazy=True,
    )
