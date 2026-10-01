from __future__ import annotations

import json
import subprocess

from fastapi import APIRouter, Query, HTTPException

from common import structlog
from common.webux.base import WebuxPluginManifest

logger = structlog.get_logger(__name__)

router = APIRouter()

_TIMEOUT = 180


def _run_watcher(*args: str, profile: str | None = None) -> subprocess.CompletedProcess:
    """Run the watcher CLI and return the completed process.

    List-form argv (no shell), so query params cannot inject commands.
    """
    cmd = ["watcher"]
    if profile:
        cmd += ["-P", profile]
    cmd += list(args)
    logger.info("watcher_exec", cmd=" ".join(cmd))
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="watcher CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="watcher timed out") from exc


def _failure(proc: subprocess.CompletedProcess) -> str:
    return ((proc.stderr or proc.stdout) or "watcher failed").strip()[-500:]


@router.get("/dashboard")
def dashboard(
    last: int = Query(3, ge=0, le=50),
    profile: str | None = Query(None),
) -> dict:
    """Live watchlist values plus latest news (mirrors `watcher dashboard --json`)."""
    proc = _run_watcher("dashboard", "--json", "--last", str(last), profile=profile)
    try:
        data = json.loads(proc.stdout)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_failure(proc)) from exc
    data["exit_code"] = proc.returncode
    logger.info("watcher_dashboard", variables=len(data.get("variables", [])), exit_code=proc.returncode)
    return data


@router.get("/history")
def history(
    variable: str = Query(...),
    since: str = Query("30d"),
    profile: str | None = Query(None),
) -> dict:
    """Observations for one variable (mirrors `watcher history <id> --json`)."""
    proc = _run_watcher("history", variable, "--json", "--since", since, profile=profile)
    if proc.returncode != 0:
        err = _failure(proc)
        if "Unknown variable" in err:
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=502, detail=err)
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_failure(proc)) from exc


@router.get("/news")
def news(
    variable: str = Query(...),
    limit: int = Query(10, ge=0, le=50),
    profile: str | None = Query(None),
) -> dict:
    """News for one variable's topics (mirrors `watcher news --variable <id> --json`)."""
    proc = _run_watcher("news", "--variable", variable, "--json", "--limit", str(limit), profile=profile)
    if proc.returncode != 0:
        err = _failure(proc)
        if "Unknown variable" in err:
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=502, detail=err)
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_failure(proc)) from exc


_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Watcher</title>
<style>
:root { --bg:#1a1a2e; --surface:#16213e; --accent:#0f3460; --text:#eee; --text-dim:#9ca3af; --border:#334155; --success:#22c55e; --error:#ef4444; --warning:#f59e0b; }
body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }
input, button, select { padding:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:6px; }
button { cursor:pointer; }
button:hover { background:var(--accent); }
h2 { margin:0 0 12px 0; }
.row { display:flex; gap:8px; margin-bottom:12px; align-items:center; flex-wrap:wrap; }
table { width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--border); border-radius:8px; overflow:hidden; }
th, td { padding:10px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:14px; }
th { color:var(--text-dim); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
tr.clickable { cursor:pointer; }
tr.clickable:hover td { background:rgba(255,255,255,.03); }
.val { font-weight:700; font-variant-numeric:tabular-nums; }
.up { color:var(--success); } .down { color:var(--error); }
.stale { color:var(--warning); font-size:11px; font-weight:700; margin-left:6px; }
.err { color:var(--error); font-size:13px; }
.dim { color:var(--text-dim); }
.news { margin-top:16px; display:flex; flex-direction:column; gap:8px; }
.news a { color:var(--text); text-decoration:none; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:10px 12px; display:block; }
.news a:hover { border-color:var(--accent); }
.news .meta { color:var(--text-dim); font-size:12px; margin-bottom:2px; }
#hist { margin-top:8px; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; display:none; }
#spinner { color:var(--text-dim); padding:24px; text-align:center; }
</style></head>
<body>
  <h2>📈 Watcher</h2>
  <div class="row">
    <label class="dim">News:</label>
    <select id="last"><option value="0">0</option><option value="3" selected>3</option><option value="5">5</option><option value="10">10</option></select>
    <label class="dim">Profile:</label>
    <input id="profile" placeholder="(active)" style="width:120px;">
    <button id="refresh">🔄 Refresh</button>
    <span class="dim" id="generated"></span>
  </div>
  <div id="out"><div id="spinner">Loading…</div></div>
  <div id="hist"><div class="row"><strong id="histTitle"></strong><span class="dim" id="histStats"></span><button id="histClose">✕</button></div><canvas id="spark" width="640" height="160" style="width:100%;height:160px;"></canvas><h4 style="margin:12px 0 6px 0;">📰 News for <span id="histNewsTitle"></span></h4><div class="news" id="histNews" style="margin-top:0;"></div></div>
  <h3>📰 News</h3>
  <div class="news" id="news"></div>
<script>
const out = document.getElementById('out');
const newsEl = document.getElementById('news');
function esc(s) { return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
function display(v, unit) { return unit === 'percent' ? String(v) + '%' : String(v) + ' ' + unit; }
function fmtChange(r) {
  if (r.change_abs == null) return '<span class="dim">—</span>';
  const cls = r.change_abs >= 0 ? 'up' : 'down';
  const sign = r.change_abs >= 0 ? '+' : '';
  return `<span class="${cls}">${sign}${r.change_abs} (${sign}${r.change_pct.toFixed(2)}%)</span>`;
}
async function load() {
  out.innerHTML = '<div id="spinner">Loading…</div>';
  newsEl.innerHTML = '';
  const last = document.getElementById('last').value;
  const profile = document.getElementById('profile').value.trim();
  const params = new URLSearchParams({last});
  if (profile) params.set('profile', profile);
  let data;
  try {
    const r = await fetch('/api/watcher/dashboard?' + params.toString());
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
  } catch (e) {
    out.innerHTML = `<div class="err">Failed: ${esc(e.message)}</div>`;
    return;
  }
  document.getElementById('generated').textContent = 'updated ' + (data.generated_at || '').slice(0, 19).replace('T', ' ');
  const rows = (data.variables || []).map(r => {
    const body = r.error
      ? `<span class="err">ERROR: ${esc(r.error)}</span>`
      : `<span class="val">${esc(display(r.value, r.unit))}</span>${r.stale ? '<span class="stale">STALE</span>' : ''}`;
    return `<tr class="clickable" data-id="${esc(r.id)}"><td><strong>${esc(r.id)}</strong><br><span class="dim">${esc(r.label || '')}</span></td><td>${body}</td><td>${fmtChange(r)}</td><td>${esc(r.as_of || '—')}</td><td class="dim">${esc(r.source || '')}</td></tr>`;
  }).join('');
  out.innerHTML = `<table><thead><tr><th>Variable</th><th>Value</th><th>Change</th><th>As of</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table>`;
  out.querySelectorAll('tr.clickable').forEach(tr => { tr.onclick = () => showHistory(tr.dataset.id, profile); });
  const items = data.news || [];
  newsEl.innerHTML = items.length ? items.map(n =>
    `<a href="${esc(n.url || '#')}" target="_blank" rel="noopener"><div class="meta">${esc(n.published_at || '')} · ${esc(n.source || '')}</div>${esc(n.title || '')}</a>`
  ).join('') : '<span class="dim">No news.</span>';
}
async function showHistory(id, profile) {
  const box = document.getElementById('hist');
  document.getElementById('histTitle').textContent = id;
  document.getElementById('histStats').textContent = 'loading…';
  box.style.display = 'block';
  box.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  const params = new URLSearchParams({variable: id, since: '90d'});
  if (profile) params.set('profile', profile);
  let data;
  try {
    const r = await fetch('/api/watcher/history?' + params.toString());
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
  } catch (e) {
    document.getElementById('histStats').textContent = 'failed: ' + e.message;
    return;
  }
  const obs = (data.observations || []).filter(o => o.value != null);
  loadHistNews(id, profile);
  if (!obs.length) { document.getElementById('histStats').textContent = 'no data'; return; }
  const vals = obs.map(o => o.value);
  document.getElementById('histStats').textContent =
    `${obs[0].date} → ${obs[obs.length-1].date} · ${obs.length} pts · min ${Math.min(...vals)} · max ${Math.max(...vals)}`;
  const c = document.getElementById('spark'), ctx = c.getContext('2d');
  const W = c.width, H = c.height, P = 8;
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = '#334155'; ctx.beginPath(); ctx.moveTo(P, H-P); ctx.lineTo(W-P, H-P); ctx.stroke();
  ctx.strokeStyle = '#4ade80'; ctx.lineWidth = 2; ctx.beginPath();
  obs.forEach((o, i) => {
    const x = P + (W - 2*P) * (obs.length === 1 ? 1 : i / (obs.length - 1));
    const y = P + (H - 2*P) * (1 - (o.value - min) / span);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}
async function loadHistNews(id, profile) {
  const box = document.getElementById('histNews');
  document.getElementById('histNewsTitle').textContent = id;
  box.innerHTML = '<span class="dim">Loading news…</span>';
  const params = new URLSearchParams({variable: id, limit: '10'});
  if (profile) params.set('profile', profile);
  try {
    const r = await fetch('/api/watcher/news?' + params.toString());
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
    const items = data.news || [];
    box.innerHTML = items.length ? items.map(n =>
      `<a href="${esc(n.url || '#')}" target="_blank" rel="noopener"><div class="meta">${esc(n.published_at || '')} · ${esc(n.source || '')}</div>${esc(n.title || '')}</a>`
    ).join('') : '<span class="dim">No news for this variable.</span>';
  } catch (e) {
    box.innerHTML = `<span class="err">News failed: ${esc(e.message)}</span>`;
  }
}
document.getElementById('refresh').onclick = load;
document.getElementById('last').onchange = load;
document.getElementById('histClose').onclick = () => { document.getElementById('hist').style.display = 'none'; };
load();
</script>
</body></html>
"""


def register(config: dict) -> WebuxPluginManifest:
    del config
    return WebuxPluginManifest(
        name="watcher",
        tab_label="Watcher",
        tab_icon="📈",
        api_router=router,
        frontend_html=_HTML,
        order=25,
        lazy=True,
    )
