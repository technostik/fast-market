from __future__ import annotations

import os
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
        "image_engine": cfg.get("image_engine", "flux2cloud"),
        "image_size": cfg.get("image_size", "landscape"),
        "image_style": cfg.get("image_style", ""),
        "narrative_style": cfg.get("narrative_style", ""),
        "animation_style": cfg.get("animation_style", "ken_burns"),
        "ken_burns_zoom_from": cfg.get("ken_burns_zoom_from", 1.0),
        "ken_burns_zoom_to": cfg.get("ken_burns_zoom_to", 1.3),
        "fps": cfg.get("fps", 24),
        "prompts": cfg.get("prompts", {}),
    }


class ConfigSaveRequest(BaseModel):
    tts_engine: str = "kokoro"
    image_engine: str = "flux2cloud"
    image_size: str = "landscape"
    image_style: str = ""
    narrative_style: str = ""
    animation_style: str = "ken_burns"
    ken_burns_zoom_from: float = 1.0
    ken_burns_zoom_to: float = 1.3
    fps: int = 24
    prompts: dict = {}


@router.post("/config")
async def save_config(req: ConfigSaveRequest):
    save_storyboard_config(req.model_dump())
    return {"ok": True}


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

/* ── Scene tree ── */
.tree-panel { flex: 0 0 auto; max-height: 40%; overflow-y: auto; padding: 8px; border-bottom: 1px solid var(--border); }
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
.detail-panel { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.detail-title { font-size: 14px; font-weight: 700; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.detail-tabs { display: flex; gap: 4px; }
.dtab { padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; background: var(--surface); color: var(--text-muted); }
.dtab.active { background: var(--accent); color: #fff; font-weight: 600; }
.dtab-content { display: none; }
.dtab-content.active { display: flex; flex-direction: column; gap: 6px; }
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
.console-header { display: flex; align-items: center; gap: 8px; padding: 4px 8px; background: var(--bg2); border-bottom: 1px solid var(--border); font-size: 11px; font-weight: 600; color: var(--text-dim); flex-shrink: 0; }
.console-body { flex: 1; overflow-y: auto; font-family: monospace; font-size: 10px; padding: 4px 8px; }
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
  <button class="btn btn-neutral" id="btnRegenMedia" onclick="regenMedia()" disabled title="Re-generate audio + images with current config, then re-clip/merge">🖼 Regen Media</button>
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
    <div class="tree-panel" id="treePanel">
      <div class="no-state" id="noState">Loading…</div>
    </div>
    <div class="detail-panel" id="detailPanel">
      <div class="no-state" style="color:var(--text-dim)">Select a scene to view details.</div>
    </div>
    <div class="console-panel">
      <div class="console-header">
        ⌨ Console
        <button class="btn-sm" onclick="clearConsoleDisplay()" style="margin-left:auto;background:var(--surface);color:var(--text)">Clear</button>
      </div>
      <div class="console-body" id="consoleBody"><span style="color:var(--text-dim)">Commands will appear here...</span></div>
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
      <div class="prompt-field">
        <div class="prompt-label">Story Breakdown Prompt</div>
        <textarea class="prompt-area" id="cfgPromptStory" rows="5"></textarea>
      </div>
      <div class="prompt-field">
        <div class="prompt-label">Scene Transcript Prompt</div>
        <textarea class="prompt-area" id="cfgPromptTranscript" rows="4"></textarea>
      </div>
      <div class="prompt-field">
        <div class="prompt-label">Scene Image Prompt</div>
        <textarea class="prompt-area" id="cfgPromptImage" rows="4"></textarea>
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

// ── Bootstrap ──────────────────────────────────────────────────────────────────
async function boot() {
  await loadConfig();
  await pollJob();
}

async function loadConfig() {
  try {
    const r = await fetch('/api/storyboard/config');
    if (!r.ok) return;
    const cfg = await r.json();
    document.getElementById('cfgTts').value = cfg.tts_engine || 'kokoro';
    document.getElementById('cfgImgEngine').value = cfg.image_engine || 'flux2cloud';
    document.getElementById('cfgImgSize').value = cfg.image_size || 'landscape';
    document.getElementById('cfgImgStyle').value = cfg.image_style || '';
    document.getElementById('cfgNarrStyle').value = cfg.narrative_style || '';
    document.getElementById('cfgFps').value = cfg.fps || 24;
    document.getElementById('cfgZoomFrom').value = cfg.ken_burns_zoom_from ?? 1.0;
    document.getElementById('cfgZoomTo').value = cfg.ken_burns_zoom_to ?? 1.3;
    document.getElementById('cfgMotion').value = cfg.ken_burns_motion || 'random';
    document.getElementById('cfgImgSeed').value = cfg.image_seed != null ? cfg.image_seed : '';
    document.getElementById('cfgImgSteps').value = cfg.image_steps != null ? cfg.image_steps : '';
    document.getElementById('cfgDraftMode').checked = cfg.draft_mode || false;
    const p = cfg.prompts || {};
    document.getElementById('cfgPromptStory').value = p.story_breakdown || '';
    document.getElementById('cfgPromptTranscript').value = p.scene_transcript || '';
    document.getElementById('cfgPromptImage').value = p.scene_image_prompt || '';
  } catch(e) { console.warn('loadConfig error', e); }
}

async function saveConfig() {
  const body = {
    tts_engine: document.getElementById('cfgTts').value,
    image_engine: document.getElementById('cfgImgEngine').value,
    image_size: document.getElementById('cfgImgSize').value,
    image_style: document.getElementById('cfgImgStyle').value,
    narrative_style: document.getElementById('cfgNarrStyle').value,
    fps: parseInt(document.getElementById('cfgFps').value) || 24,
    ken_burns_zoom_from: parseFloat(document.getElementById('cfgZoomFrom').value) || 1.0,
    ken_burns_zoom_to: parseFloat(document.getElementById('cfgZoomTo').value) || 1.3,
    ken_burns_motion: document.getElementById('cfgMotion').value,
    image_seed: document.getElementById('cfgImgSeed').value !== '' ? parseInt(document.getElementById('cfgImgSeed').value) : null,
    image_steps: document.getElementById('cfgImgSteps').value !== '' ? parseInt(document.getElementById('cfgImgSteps').value) : null,
    draft_mode: document.getElementById('cfgDraftMode').checked,
    prompts: {
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
    document.getElementById('btnRegenMedia').disabled = true;
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
  document.getElementById('btnRunAll').disabled = data.running;
  document.getElementById('btnRegenMedia').disabled = data.running || !hasScenes;
  document.getElementById('btnStop').disabled = !data.running;
  document.getElementById('btnScript').disabled = false;

  // Error banner
  updateErrorBanner(data);

  // Global steps sidebar
  renderGlobalSteps(data.global_steps || {});

  // Scene tree
  renderTree(data.chapters || []);

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

function renderTree(chapters) {
  const panel = document.getElementById('treePanel');
  if (!chapters.length) {
    panel.innerHTML = '<div class="no-state">No chapters yet. Click ▶ Run All to parse the script.</div>';
    return;
  }
  panel.innerHTML = chapters.map((ch, ci) => {
    const chSt = ch.merge_step ? ch.merge_step.status : 'pending';
    const scenesHtml = (ch.scenes || []).map(sc => {
      const dots = Object.entries(sc.steps || {}).map(([k, s]) =>
        `<div class="dot ${s.status}" title="${k}: ${s.status}"></div>`).join('');
      const sel = sc.id === selectedSceneId ? ' selected' : '';
      return `<div class="scene-row${sel}" onclick="selectScene('${sc.id}','${ch.id}')">
        <span class="scene-title">${sc.title || sc.id}</span>
        <div class="step-dots">${dots}</div>
      </div>`;
    }).join('');
    return `<div class="chapter-node">
      <div class="chapter-header" onclick="toggleChapter(this)">
        <span class="chapter-toggle">▾</span>
        <span class="chapter-title">${ch.title || ch.id}</span>
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

function renderDetail(sc, ch) {
  const panel = document.getElementById('detailPanel');
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

async function regenMedia() {
  if (state && state.running) return;
  await postRun({ from_global_step: 'audio' });
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
    document.getElementById('btnRegenMedia').disabled = true;
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
