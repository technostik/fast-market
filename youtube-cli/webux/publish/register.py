from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from common.webux.base import WebuxPluginManifest

router = APIRouter()

# ── Pipeline state ────────────────────────────────────────────────────────────

STEP_NAMES = [
    "Remove silence",
    "Extract transcript",
    "Burn subtitles",
    "Generate title & description",
    "Upload to YouTube",
]


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
    steps: list[Step] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    title: str = ""
    description: str = ""
    status: str = "running"
    video_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "video_url": self.video_url,
            "title": self.title,
            "description": self.description,
            "files": self.files,
            "steps": [
                {"name": s.name, "status": s.status, "output": s.output}
                for s in self.steps
            ],
        }


_jobs: dict[str, Job] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _yt() -> str:
    return shutil.which("youtube") or "youtube"


def _pr() -> str:
    return shutil.which("prompt") or "prompt"


def _stem(p: str) -> str:
    return Path(p).stem


def _dir(p: str) -> Path:
    return Path(p).resolve().parent


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
        s0.status = "done"
        current_video = out_path
        job.files["no_silence"] = out_path
    else:
        s0.status = "skipped"

    # Step 1 — Extract transcript
    s1 = job.steps[1]
    s1.status = "running"
    srt_path = str(d / f"{stem}.srt")
    rc, _ = await _run(
        s1, _yt(), "extract-transcript", current_video,
        "-o", srt_path, "-l", job.language, "-m", job.model,
    )
    if rc != 0:
        s1.status = "error"
        job.status = "error"
        return
    s1.status = "done"
    job.files["transcript"] = srt_path

    # Step 2 — Burn subtitles
    s2 = job.steps[2]
    if job.do_burn_subtitles:
        s2.status = "running"
        out_path = str(d / f"{stem}_subtitled.mp4")
        rc, _ = await _run(
            s2, _yt(), "burn-subtitles", current_video, srt_path, "-o", out_path
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
    await _run_from_llm(job, srt_path, current_video)


async def _run_from_llm(job: Job, srt_path: str, final_video: str) -> None:
    """Resumable entry point: run LLM step then upload."""
    # Step 3 — Prompt apply
    s3 = job.steps[3]
    s3.status = "running"

    rc, title_out = await _run(s3, _pr(), "apply", job.prompt_title, f"transcript=@{srt_path}")
    if rc != 0:
        s3.status = "error"
        job.status = "error"
        return

    proc = await asyncio.create_subprocess_exec(
        _pr(), "apply", job.prompt_summary, f"transcript=@{srt_path}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    desc_out, desc_err = await proc.communicate()
    if proc.returncode:
        s3.output += "\n" + desc_err.decode(errors="replace")
        s3.status = "error"
        job.status = "error"
        return

    job.title = title_out.strip()
    job.description = desc_out.decode(errors="replace").strip()
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
    job.video_url = url_out.strip()
    job.status = "done"


# ── API ───────────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    source: str
    prompt_title: str
    prompt_summary: str
    do_remove_silence: bool = True
    do_burn_subtitles: bool = True
    language: str = "fr"
    model: str = "large-v3"
    privacy: str = "unlisted"


class ResumeRequest(BaseModel):
    source: str
    prompt_title: str
    prompt_summary: str
    privacy: str = "unlisted"


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
    srt_path = str(_dir(source) / f"{_stem(source)}.srt")
    if not Path(srt_path).exists():
        raise HTTPException(status_code=400, detail=f"Transcript not found: {srt_path}")

    d = _dir(source)
    stem = _stem(source)
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
        model="large-v3",
        privacy=req.privacy,
        steps=[Step(name=n) for n in STEP_NAMES],
        files={"transcript": srt_path, "final_video": final_video},
    )
    for i in range(3):
        job.steps[i].status = "skipped"
    _jobs[job_id] = job
    asyncio.create_task(_run_from_llm(job, srt_path, final_video))
    return {"job_id": job_id}


@router.post("/check-resume")
async def check_resume(body: dict):
    source = str(Path(body.get("source", "")).expanduser().resolve())
    srt = _dir(source) / f"{_stem(source)}.srt"
    return {"can_resume": srt.exists(), "transcript": str(srt)}


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
    }
    body { margin:0; padding:16px; background:var(--bg); color:var(--text);
           font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
    h2 { margin:0 0 16px; font-size:18px; }
    label { display:block; font-size:12px; color:var(--dim); margin-bottom:3px; }
    input[type=text], select {
      width:100%; padding:8px 10px; border:1px solid var(--border);
      background:var(--bg2); color:var(--text); border-radius:6px;
      box-sizing:border-box; font-size:13px;
    }
    .row { margin-bottom:12px; }
    .cols { display:flex; gap:12px; }
    .cols .row { flex:1; }
    .checkrow { display:flex; align-items:center; gap:8px; margin-bottom:8px; font-size:13px; }
    button { padding:8px 16px; border:none; border-radius:6px; cursor:pointer; font-size:13px; font-weight:600; }
    .btn-go     { background:var(--ok); color:#000; }
    .btn-go:hover { opacity:.88; }
    .btn-go:disabled { opacity:.4; cursor:default; }
    .btn-resume { background:var(--warn); color:#000; display:none; }
    .btn-resume:hover { opacity:.88; }
    .steps { margin:18px 0 10px; }
    .step { display:flex; align-items:flex-start; gap:10px; padding:7px 0;
            border-bottom:1px solid var(--border); font-size:13px; }
    .step:last-child { border-bottom:none; }
    .step-icon { width:20px; flex-shrink:0; font-size:14px; margin-top:1px; }
    .step-name { flex:1; }
    .step-out { font-size:11px; color:var(--dim); margin-top:2px; word-break:break-all; }
    .log-box { background:#0f172a; border:1px solid var(--border); border-radius:8px;
               padding:10px; font-size:12px; font-family:monospace; white-space:pre-wrap;
               max-height:220px; overflow-y:auto; margin-top:12px; display:none; }
    .result { margin-top:14px; padding:12px; border-radius:8px;
              background:var(--bg2); border:1px solid var(--ok); display:none; }
    .result a { color:var(--ok); }
    .hint { font-size:11px; color:var(--dim); margin-left:8px; }
    hr { border:none; border-top:1px solid var(--border); margin:18px 0; }
  </style>
</head>
<body>
  <h2>🚀 Publish</h2>

  <div class="row">
    <label>Source MP4 (absolute path)</label>
    <input type="text" id="source" placeholder="/path/to/recording.mp4" />
  </div>
  <div class="cols">
    <div class="row">
      <label>Prompt — title</label>
      <input type="text" id="promptTitle" placeholder="youtube-title" />
    </div>
    <div class="row">
      <label>Prompt — description</label>
      <input type="text" id="promptSummary" placeholder="youtube-summary" />
    </div>
  </div>
  <div class="cols" style="align-items:flex-end">
    <div class="row" style="flex:0 0 auto">
      <label>Language</label>
      <input type="text" id="language" value="fr" style="width:60px" />
    </div>
    <div class="row" style="flex:0 0 auto">
      <label>Whisper model</label>
      <input type="text" id="model" value="large-v3" style="width:110px" />
    </div>
    <div class="row" style="flex:0 0 auto">
      <label>Privacy</label>
      <select id="privacy" style="width:110px">
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
    <button class="btn-resume" id="resumeBtn">↩ Reprendre la publication</button>
    <span class="hint" id="resumeHint"></span>
  </div>

  <hr />

  <div class="steps" id="stepsEl">
    <div class="step" id="step-0"><span class="step-icon">⬜</span><div><div class="step-name">Remove silence</div><div class="step-out" id="out-0"></div></div></div>
    <div class="step" id="step-1"><span class="step-icon">⬜</span><div><div class="step-name">Extract transcript</div><div class="step-out" id="out-1"></div></div></div>
    <div class="step" id="step-2"><span class="step-icon">⬜</span><div><div class="step-name">Burn subtitles</div><div class="step-out" id="out-2"></div></div></div>
    <div class="step" id="step-3"><span class="step-icon">⬜</span><div><div class="step-name">Generate title &amp; description</div><div class="step-out" id="out-3"></div></div></div>
    <div class="step" id="step-4"><span class="step-icon">⬜</span><div><div class="step-name">Upload to YouTube</div><div class="step-out" id="out-4"></div></div></div>
  </div>

  <div class="result" id="result">
    <strong>✅ Published!</strong><br/>
    <a id="resultUrl" href="#" target="_blank"></a>
    <div id="resultTitle" style="font-size:12px;color:var(--dim);margin-top:4px"></div>
  </div>
  <div class="log-box" id="logBox"></div>

<script>
const ICONS = { pending:'⬜', running:'🔄', done:'✅', error:'❌', skipped:'⏭️' };
let pollTimer = null;
let jobId = null;

function renderSteps(steps) {
  steps.forEach((s, i) => {
    const icon = document.querySelector(`#step-${i} .step-icon`);
    const out  = document.getElementById(`out-${i}`);
    if (icon) icon.textContent = ICONS[s.status] || '⬜';
    if (out)  out.textContent  = s.output || '';
  });
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
  document.getElementById('result').style.display = 'none';
  document.getElementById('logBox').style.display  = 'none';
  document.getElementById('logBox').textContent    = '';
  document.getElementById('resumeBtn').style.display = 'none';
  document.getElementById('resumeHint').textContent  = '';
  for (let i = 0; i < 5; i++) {
    document.querySelector(`#step-${i} .step-icon`).textContent = '⬜';
    document.getElementById(`out-${i}`).textContent = '';
  }
}

async function poll() {
  if (!jobId) return;
  const r = await fetch(`/api/publish/status/${jobId}`).catch(() => null);
  if (!r || !r.ok) return;
  const data = await r.json();
  renderSteps(data.steps);
  if (data.status === 'done') {
    stopPoll();
    document.getElementById('startBtn').disabled = false;
    const res = document.getElementById('result');
    document.getElementById('resultUrl').href        = data.video_url;
    document.getElementById('resultUrl').textContent = data.video_url;
    document.getElementById('resultTitle').textContent = data.title;
    res.style.display = 'block';
  } else if (data.status === 'error') {
    stopPoll();
    document.getElementById('startBtn').disabled = false;
    checkResume();
  }
}

async function checkResume() {
  const src = document.getElementById('source').value.trim();
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
  const src   = document.getElementById('source').value.trim();
  const pt    = document.getElementById('promptTitle').value.trim();
  const ps    = document.getElementById('promptSummary').value.trim();
  const priv  = document.getElementById('privacy').value;
  if (!src || !pt || !ps) { alert('Fill in source file and both prompt names.'); return; }

  resetUI();
  document.getElementById('startBtn').disabled = true;

  const url  = isResume ? '/api/publish/resume' : '/api/publish/start';
  const body = isResume
    ? { source:src, prompt_title:pt, prompt_summary:ps, privacy:priv }
    : {
        source:src, prompt_title:pt, prompt_summary:ps, privacy:priv,
        do_remove_silence: document.getElementById('doSilence').checked,
        do_burn_subtitles: document.getElementById('doBurn').checked,
        language: document.getElementById('language').value.trim() || 'fr',
        model:    document.getElementById('model').value.trim() || 'large-v3',
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
document.getElementById('source').addEventListener('blur', checkResume);
</script>
</body>
</html>"""


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
