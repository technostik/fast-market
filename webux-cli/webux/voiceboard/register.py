from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest

from .config import load_voiceboard_config, save_voiceboard_config
from .models import ProjectState
from .pipeline import (
    start_pipeline, stop_pipeline, is_running,
    get_current_state, _find_scene,
)

router = APIRouter()

# ── State helpers ─────────────────────────────────────────────────────────────

def _state_path(config: dict) -> Path:
    workdir = config.get("workdir") or ""
    if not workdir:
        raise HTTPException(status_code=400, detail="workdir not set in common config — run toolsetup")
    return Path(workdir).expanduser() / "voiceboard" / "state.json"


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
    cfg = load_voiceboard_config()
    return cfg


class ConfigSaveRequest(BaseModel):
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
    language: str = "en"
    transcript_engine: str = "whisperx"
    transcript_model: str = "medium"
    segment_min: float = 10.0
    segment_max: float = 30.0
    segment_silence: float = 0.6
    voice_file: str = ""
    segments_json: str = ""
    prompts: dict = {}


@router.post("/config")
async def save_config(req: ConfigSaveRequest):
    save_voiceboard_config(req.model_dump())
    return {"ok": True}


@router.get("/state")
async def get_state():
    cfg = load_voiceboard_config()
    state = _load_state(cfg)
    if state is None:
        return {"initialized": False}
    return {"initialized": True, **state.to_dict(), "global_steps": state.global_step_summary()}


class InitRequest(BaseModel):
    voice_file: str = ""
    segments_json: str = ""
    transcript_engine: str = "whisperx"
    transcript_model: str = "medium"
    language: str = "en"
    segment_min: float = 10.0
    segment_max: float = 30.0
    segment_silence: float = 0.6


@router.post("/init")
async def init_project(req: InitRequest):
    if not req.voice_file.strip() and not req.segments_json.strip():
        raise HTTPException(status_code=400, detail="Provide a voice_file or a segments_json path")

    # Persist ingestion params so /run can read them back.
    save_voiceboard_config({
        "voice_file": req.voice_file.strip(),
        "segments_json": req.segments_json.strip(),
        "transcript_engine": req.transcript_engine,
        "transcript_model": req.transcript_model,
        "language": req.language,
        "segment_min": req.segment_min,
        "segment_max": req.segment_max,
        "segment_silence": req.segment_silence,
    })

    cfg = load_voiceboard_config()
    sp = _state_path(cfg)
    workdir = str(sp.parent)
    Path(workdir).mkdir(parents=True, exist_ok=True)

    state = ProjectState(script_text="", workdir=workdir)
    state.save(sp)
    return {"initialized": True, **state.to_dict(), "global_steps": state.global_step_summary()}


class RunRequest(BaseModel):
    from_global_step: str | None = None
    only_global_step: str | None = None
    scene_id: str | None = None
    from_step: str | None = None
    only_step: bool = False
    only_scene: bool = False


@router.post("/run")
async def run_pipeline(req: RunRequest):
    if is_running():
        raise HTTPException(status_code=409, detail="Pipeline already running")
    cfg = load_voiceboard_config()
    state = _load_state(cfg)
    if state is None:
        raise HTTPException(status_code=400, detail="Project not initialized — call /init first")
    sp = _state_path(cfg)
    start_pipeline(
        state, sp, cfg,
        from_global_step=req.from_global_step,
        only_global_step=req.only_global_step,
        scene_id=req.scene_id,
        from_step=req.from_step,
        only_step=req.only_step,
        only_scene=req.only_scene,
    )
    return {"ok": True, "running": True}


@router.post("/stop")
async def stop():
    stop_pipeline()
    return {"ok": True}


@router.get("/job")
async def poll_job():
    cfg = load_voiceboard_config()
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
    cfg = load_voiceboard_config()
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
        sc.raw_description = req.transcript
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "transcript.txt").write_text(sc.transcript, encoding="utf-8")
    if req.image_prompt is not None:
        sc.image_prompt = req.image_prompt
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "image_prompt.txt").write_text(sc.image_prompt, encoding="utf-8")
    state.save(_state_path(cfg))
    return {"ok": True}


_MIME = {
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".mov": "video/quicktime",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
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
<title>Voiceboard</title>
<style>
:root {
  --bg:#1e1e2e; --bg2:#181825; --bg3:#11111b; --surface:#313244; --surface2:#45475a;
  --text:#cdd6f4; --text-dim:#6c7086; --text-muted:#9399b2;
  --accent:#89b4fa; --green:#a6e3a1; --red:#f38ba8; --yellow:#f9e2af; --border:#313244;
}
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg3); color:var(--text); font-family:system-ui,sans-serif; font-size:13px; height:100vh; display:flex; flex-direction:column; overflow:hidden; }
.topbar { display:flex; align-items:center; gap:8px; padding:8px 12px; background:var(--bg2); border-bottom:1px solid var(--border); flex-shrink:0; flex-wrap:wrap; }
.topbar input[type=text], .topbar select { background:var(--bg3); border:1px solid var(--surface2); border-radius:4px; padding:5px 8px; color:var(--text); font-size:12px; }
.topbar label { font-size:11px; color:var(--text-dim); }
.btn { padding:5px 12px; border-radius:4px; border:none; cursor:pointer; font-size:12px; font-weight:600; }
.btn:disabled { opacity:.4; cursor:default; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-danger { background:var(--red); color:#fff; }
.btn-neutral { background:var(--surface); color:var(--text); }
.status-badge { font-size:11px; padding:3px 8px; border-radius:12px; font-weight:600; }
.s-idle { background:var(--surface); color:var(--text-muted); }
.s-running { background:var(--accent); color:#fff; }
.s-done { background:var(--green); color:#1e1e2e; }
.s-error { background:var(--red); color:#fff; }
.s-partial { background:var(--yellow); color:#1e1e2e; }
.workdir-label { color:var(--text-dim); font-size:11px; max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.main { flex:1; display:flex; overflow:hidden; }
.side { width:230px; background:var(--bg2); border-right:1px solid var(--border); overflow-y:auto; padding:10px; flex-shrink:0; }
.side h3 { font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--text-dim); margin:8px 0 4px; }
.side input, .side select, .side textarea { width:100%; background:var(--bg3); border:1px solid var(--surface2); border-radius:4px; padding:4px 6px; color:var(--text); font-size:12px; margin-bottom:6px; }
.side .row { display:flex; gap:6px; }
.side .row > * { flex:1; }
.content { flex:1; display:flex; flex-direction:column; overflow:hidden; }
.error-banner { display:none; background:var(--red); color:#fff; padding:6px 12px; font-size:12px; font-weight:600; }
.error-banner.visible { display:block; }
.matrix { flex:1; overflow-y:auto; padding:10px; display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:10px; align-content:start; }
.scene { background:var(--bg2); border:1px solid var(--border); border-radius:6px; overflow:hidden; display:flex; flex-direction:column; }
.scene-head { display:flex; align-items:center; gap:6px; padding:5px 8px; background:var(--surface); font-size:11px; font-weight:600; }
.scene-head .idx { color:var(--accent); }
.scene-body { padding:8px; display:flex; flex-direction:column; gap:6px; }
.scene img { width:100%; height:140px; object-fit:cover; background:var(--bg3); border-radius:4px; }
.scene .ph { width:100%; height:140px; background:var(--bg3); border-radius:4px; display:flex; align-items:center; justify-content:center; color:var(--text-dim); font-size:11px; }
.scene textarea { width:100%; background:var(--bg3); border:1px solid var(--surface2); border-radius:4px; color:var(--text); font-size:11px; padding:4px; resize:vertical; min-height:46px; }
.scene audio { width:100%; }
.scene .acts { display:flex; gap:4px; flex-wrap:wrap; }
.scene .acts .btn { padding:3px 6px; font-size:10px; border-radius:3px; }
.config-body { display:none; }
.config-body.open { display:block; }
.console { height:160px; background:var(--bg3); border-top:1px solid var(--border); overflow-y:auto; padding:6px 8px; font-family:monospace; font-size:11px; }
.console-entry { margin-bottom:3px; }
.console-ts { color:var(--text-dim); }
.console-cmd { color:var(--accent2); }
.console-ok { color:var(--text-muted); white-space:pre-wrap; }
.console-err { color:var(--red); white-space:pre-wrap; }
.final-wrap { padding:8px; display:none; }
.final-wrap.visible { display:block; }
</style>
</head>
<body>
<div class="topbar">
  <strong>🎙 Voiceboard</strong>
  <span id="statusBadge" class="status-badge s-idle">idle</span>
  <button id="btnSegment" class="btn btn-primary" onclick="initAndSegment()">1. Segment &amp; Ingest</button>
  <button id="btnImages" class="btn btn-primary" onclick="runFrom('image_prompt')">2. Generate Images</button>
  <button id="btnBuild" class="btn btn-primary" onclick="runFull()">3. Build Video</button>
  <button id="btnStop" class="btn btn-danger" onclick="stopPipeline()">Stop</button>
  <span class="workdir-label" id="workdirLabel"></span>
</div>

<div class="error-banner" id="errorBanner"></div>

<div class="main">
  <div class="side">
    <h3>Voice source</h3>
    <label>Voice file (.ogg/.mp3/.mp4/.wav)</label>
    <input type="text" id="voiceFile" placeholder="/path/to/voice.mp4" />
    <label>…or existing segments.json</label>
    <input type="text" id="segmentsJson" placeholder="/path/to/segments.json" />
    <div class="row">
      <div><label>Engine</label><select id="transcriptEngine"><option value="whisperx">whisperx</option><option value="groq">groq</option></select></div>
      <div><label>Model</label><input type="text" id="transcriptModel" value="medium" /></div>
    </div>
    <div class="row">
      <div><label>Lang</label><input type="text" id="language" value="en" /></div>
      <div><label>Silence</label><input type="text" id="segmentSilence" value="0.6" /></div>
    </div>
    <div class="row">
      <div><label>Min seg (s)</label><input type="text" id="segmentMin" value="10" /></div>
      <div><label>Max seg (s)</label><input type="text" id="segmentMax" value="30" /></div>
    </div>

    <h3>Image &amp; animation</h3>
    <label>Engine</label><input type="text" id="imageEngine" value="flux2cloud" />
    <label>Size</label>
    <select id="imageSize">
      <option>landscape</option><option>square</option><option>portrait</option><option>youtube</option><option>wide</option>
    </select>
    <label>Image style</label><textarea id="imageStyle" rows="2"></textarea>
    <label>Motion</label>
    <select id="kenBurnsMotion">
      <option>random</option><option>zoom_in</option><option>zoom_out</option><option>pan_right</option><option>pan_left</option><option>pan_up</option><option>pan_down</option>
    </select>
    <div class="row">
      <div><label>Zoom from</label><input type="text" id="kbZoomFrom" value="1.0" /></div>
      <div><label>Zoom to</label><input type="text" id="kbZoomTo" value="1.3" /></div>
    </div>
    <div class="row">
      <div><label>FPS</label><input type="text" id="fps" value="24" /></div>
      <div><label>Transition</label>
        <select id="chapterTransition"><option>none</option><option>fade</option><option>crossfade</option><option>random</option></select>
      </div>
    </div>
    <label class="chk"><input type="checkbox" id="draftMode" /> Draft mode (fast)</label>
    <button class="btn btn-neutral" style="width:100%;margin-top:6px" onclick="saveConfig()">Save config</button>
  </div>

  <div class="content">
    <div class="matrix" id="matrix"></div>
    <div class="final-wrap" id="finalWrap">
      <strong>Final video:</strong>
      <video id="finalVideo" controls style="max-height:200px"></video>
      <a id="finalDownload" href="#">download</a>
    </div>
    <div class="console" id="consoleBody"></div>
  </div>
</div>

<script>
let state = null, configOpen = false, _consoleClear = 0;
let _lastMatrixJson = null, _matrixBusy = false;

function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function api(p, opts){ return fetch('/api/voiceboard'+p, opts); }
function previewUrl(p){ return '/api/voiceboard/preview?file='+encodeURIComponent(p); }
function statusClass(s){ return ({pending:'s-idle',running:'s-running',done:'s-done',error:'s-error',skipped:'s-idle',partial:'s-partial'})[s]||'s-idle'; }

async function loadConfig(){
  const r = await api('/config'); const c = await r.json();
  document.getElementById('voiceFile').value = c.voice_file||'';
  document.getElementById('segmentsJson').value = c.segments_json||'';
  document.getElementById('transcriptEngine').value = c.transcript_engine||'whisperx';
  document.getElementById('transcriptModel').value = c.transcript_model||'medium';
  document.getElementById('language').value = c.language||'en';
  document.getElementById('segmentSilence').value = c.segment_silence??0.6;
  document.getElementById('segmentMin').value = c.segment_min??10;
  document.getElementById('segmentMax').value = c.segment_max??30;
  document.getElementById('imageEngine').value = c.image_engine||'flux2cloud';
  document.getElementById('imageSize').value = c.image_size||'landscape';
  document.getElementById('imageStyle').value = c.image_style||'';
  document.getElementById('kenBurnsMotion').value = c.ken_burns_motion||'random';
  document.getElementById('kbZoomFrom').value = c.ken_burns_zoom_from??1.0;
  document.getElementById('kbZoomTo').value = c.ken_burns_zoom_to??1.3;
  document.getElementById('fps').value = c.fps??24;
  document.getElementById('chapterTransition').value = c.chapter_transition||'none';
  document.getElementById('draftMode').checked = !!c.draft_mode;
}

async function saveConfig(){
  const body = {
    voice_file: document.getElementById('voiceFile').value,
    segments_json: document.getElementById('segmentsJson').value,
    transcript_engine: document.getElementById('transcriptEngine').value,
    transcript_model: document.getElementById('transcriptModel').value,
    language: document.getElementById('language').value,
    segment_silence: parseFloat(document.getElementById('segmentSilence').value),
    segment_min: parseFloat(document.getElementById('segmentMin').value),
    segment_max: parseFloat(document.getElementById('segmentMax').value),
    image_engine: document.getElementById('imageEngine').value,
    image_size: document.getElementById('imageSize').value,
    image_style: document.getElementById('imageStyle').value,
    ken_burns_motion: document.getElementById('kenBurnsMotion').value,
    ken_burns_zoom_from: parseFloat(document.getElementById('kbZoomFrom').value),
    ken_burns_zoom_to: parseFloat(document.getElementById('kbZoomTo').value),
    fps: parseInt(document.getElementById('fps').value),
    chapter_transition: document.getElementById('chapterTransition').value,
    draft_mode: document.getElementById('draftMode').checked,
  };
  await api('/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  schedulePoll(200);
}

async function initAndSegment(){
  const body = {
    voice_file: document.getElementById('voiceFile').value,
    segments_json: document.getElementById('segmentsJson').value,
    transcript_engine: document.getElementById('transcriptEngine').value,
    transcript_model: document.getElementById('transcriptModel').value,
    language: document.getElementById('language').value,
    segment_min: parseFloat(document.getElementById('segmentMin').value),
    segment_max: parseFloat(document.getElementById('segmentMax').value),
    segment_silence: parseFloat(document.getElementById('segmentSilence').value),
  };
  if (!body.voice_file && !body.segments_json){ alert('Provide a voice file or segments.json'); return; }
  await api('/init', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  await api('/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({only_global_step:'segment'})});
  schedulePoll(200);
}

async function runFull(){ await api('/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({})}); schedulePoll(200); }
async function runFrom(step){ await api('/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({from_global_step:step})}); schedulePoll(200); }
function stopPipeline(){ api('/stop', {method:'POST'}); schedulePoll(200); }

async function runScene(id, fromStep, onlyStep, onlyScene){
  await api('/run', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({scene_id:id, from_step:fromStep, only_step:!!onlyStep, only_scene:!!onlyScene})});
  schedulePoll(200);
}

async function saveSceneText(id){
  const tr = document.getElementById('tx_'+id).value;
  const ip = document.getElementById('ip_'+id).value;
  await api('/scene/'+id, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({transcript:tr, image_prompt:ip})});
}

function matrixBusy(){
  const el = document.getElementById('matrix');
  if (!el) return false;
  const a = document.activeElement;
  if (a && el.contains(a) && (a.tagName==='TEXTAREA'||a.tagName==='INPUT')) return true;
  return [...el.querySelectorAll('audio,video')].some(m=>!m.paused);
}

function renderMatrix(){
  if (!state || !state.chapters) return;
  const scenes = [];
  state.chapters.forEach(ch => (ch.scenes||[]).forEach(sc => scenes.push(sc)));
  if (!scenes.length){ document.getElementById('matrix').innerHTML = '<div style="color:var(--text-dim)">No scenes yet — run "Segment &amp; Ingest".</div>'; return; }
  document.getElementById('matrix').innerHTML = scenes.map(sc => {
    const st = sc.steps||{};
    const img = sc.image_file ? `<img src="${previewUrl(sc.image_file)}" />` : `<div class="ph">no image</div>`;
    const aud = sc.audio_file ? `<audio controls src="${previewUrl(sc.audio_file)}"></audio>` : '';
    const dur = sc.audio_duration!=null ? sc.audio_duration+'s' : '';
    return `<div class="scene" id="scene_${sc.id}">
      <div class="scene-head"><span class="idx">${esc(sc.id)}</span>
        <span class="status-badge ${statusClass(st.gen_image_prompt?st.gen_image_prompt.status:'pending')}">${(st.gen_image_prompt?st.gen_image_prompt.status:'pending')}</span>
        <span style="color:var(--text-dim)">${dur}</span></div>
      <div class="scene-body">
        ${img}
        ${aud}
        <textarea id="tx_${sc.id}" placeholder="narration text">${esc(sc.transcript||'')}</textarea>
        <textarea id="ip_${sc.id}" placeholder="image prompt (LLM-generated)">${esc(sc.image_prompt||'')}</textarea>
        <div class="acts">
          <button class="btn btn-neutral" onclick="runScene('${sc.id}','gen_image_prompt',true,false)">Prompt</button>
          <button class="btn btn-neutral" onclick="runScene('${sc.id}','gen_image_prompt',false,true)">Img+Clip</button>
          <button class="btn btn-neutral" onclick="runScene('${sc.id}','gen_image',true,false)">Image</button>
          <button class="btn btn-neutral" onclick="runScene('${sc.id}','assemble_clip',true,false)">Clip</button>
          <button class="btn btn-neutral" onclick="saveSceneText('${sc.id}')">Save</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

function renderConsole(entries){
  const body = document.getElementById('consoleBody');
  if (!body) return;
  const visible = (entries||[]).slice(_consoleClear);
  if (!visible.length) return;
  body.innerHTML = visible.map(e=>{
    const t = new Date(e.t*1000).toTimeString().slice(0,8);
    const ok = e.rc===0 || e.rc==null;
    const rcBadge = e.rc!=null ? ` <span style="color:${ok?'var(--green)':'var(--red)'}">[${e.rc}]</span>` : '';
    const out = e.output ? `<div class="${ok?'console-ok':'console-err'}">${esc(e.output.slice(-800))}</div>` : '';
    return `<div class="console-entry"><span class="console-ts">[${t}]</span> <span class="console-cmd">${esc(e.cmd)}</span>${rcBadge}${out}</div>`;
  }).join('');
  if (body.scrollHeight - body.scrollTop - body.clientHeight < 60) body.scrollTop = body.scrollHeight;
}

function applyState(data){
  state = data;
  const running = data.running;
  const gs = data.global_steps||{};
  const overall = running ? 'running' : (gs.parse==='error'||Object.values(gs).some(s=>s==='error') ? 'error' : (gs.final==='done'?'done':'idle'));
  const badge = document.getElementById('statusBadge');
  badge.className = 'status-badge '+statusClass(overall);
  badge.textContent = running ? 'running' : overall;
  document.getElementById('btnSegment').disabled = running;
  document.getElementById('btnImages').disabled = running;
  document.getElementById('btnBuild').disabled = running;
  document.getElementById('btnStop').disabled = !running;

  document.getElementById('errorBanner').className = 'error-banner' + (Object.values(gs).some(s=>s==='error')?' visible':'');

  const j = JSON.stringify(scenesFingerprint(data));
  if (j!==_lastMatrixJson && !matrixBusy()){ _lastMatrixJson=j; renderMatrix(); }
  else if (j!==_lastMatrixJson){ setTimeout(()=>{ if(JSON.stringify(scenesFingerprint(state))!==_lastMatrixJson) {_lastMatrixJson=j; renderMatrix();} }, 1500); }

  const finalW = document.getElementById('finalWrap');
  if (data.final_file){ finalW.className='final-wrap visible'; document.getElementById('finalVideo').src = previewUrl(data.final_file); document.getElementById('finalDownload').href = '/api/voiceboard/download?file='+encodeURIComponent(data.final_file); }
  else finalW.className='final-wrap';

  renderConsole(data.console_log);
}

function scenesFingerprint(data){
  if (!data.chapters) return [];
  return data.chapters.flatMap(ch=>(ch.scenes||[]).map(sc=>({i:sc.id,t:sc.transcript,ip:sc.image_prompt,img:sc.image_file,st:Object.fromEntries(Object.entries(sc.steps||{}).map(([k,v])=>[k,v.status]))})));
}

let _pollTimer=null;
function schedulePoll(ms){ clearTimeout(_pollTimer); _pollTimer=setTimeout(poll, ms||1500); }
async function poll(){
  try{
    const r = await api('/job'); const d = await r.json();
    applyState(d);
  }catch(e){}
  if (state && state.running) schedulePoll(1200); else schedulePoll(2500);
}

(async ()=>{ await loadConfig(); const r = await api('/state'); const d = await r.json(); applyState(d); schedulePoll(1500); })();
</script>
</body>
</html>"""


def register(config: dict) -> WebuxPluginManifest:
    return WebuxPluginManifest(
        name="voiceboard",
        tab_label="Voiceboard",
        tab_icon="🎙",
        api_router=router,
        frontend_html=_HTML,
        order=70,
        lazy=True,
    )
