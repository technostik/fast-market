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
    refresh: bool = Query(False),
    main_currency: str = Query("USD"),
) -> dict:
    """Live watchlist values plus latest news (mirrors `watcher dashboard --json`).

    Without refresh=true, values fetched less than 1h ago are served from storage.
    main_currency is USD or EUR (anything else falls back to USD).
    """
    args = ["dashboard", "--json", "--last", str(last)]
    if refresh:
        args.append("--refresh")
    args += ["--main-currency", main_currency if main_currency in ("EUR", "USD") else "USD"]
    proc = _run_watcher(*args, profile=profile)
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
/* Theme vars (:root) are injected by the webux hub (see /theme.css). */
body { margin:0; padding:0; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }
input, button, select { padding:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:6px; }
button { cursor:pointer; }
button:hover { background:var(--accent); }
h2 { margin:0 0 12px 0; }
.row { display:flex; gap:8px; margin-bottom:12px; align-items:center; flex-wrap:wrap; }
.split { display:flex; gap:12px; align-items:flex-start; }
#out { flex:1 1 auto; min-width:0; }
.cards-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:10px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; cursor:pointer; }
.card:hover { border-color:var(--accent); }
.card.selected { border-color:var(--accent); }
.card:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.card-head { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.card-id { font-weight:700; }
.card-icon { font-size:20px; margin-right:6px; }
.card-label { font-size:12px; margin-top:2px; }
.card-value { font-size:20px; font-weight:700; margin:8px 0 4px 0; font-variant-numeric:tabular-nums; }
.card-foot { display:flex; justify-content:space-between; gap:8px; font-size:12px; margin-top:6px; }
.val { font-weight:700; font-variant-numeric:tabular-nums; }
.up { color:var(--success); } .down { color:var(--error); }
.stale { color:var(--warning); font-size:11px; font-weight:700; margin-left:6px; }
.err { color:var(--error); font-size:13px; }
.dim { color:var(--text-dim); }
.news { margin-top:16px; display:flex; flex-direction:column; gap:8px; }
.news a { color:var(--text); text-decoration:none; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:10px 12px; display:block; }
.news a:hover { border-color:var(--accent); }
.news .meta { color:var(--text-dim); font-size:12px; margin-bottom:2px; }
#detail { flex:0 0 460px; width:460px; max-width:48%; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; display:none; position:sticky; top:12px; }
#newsPager { margin:8px 0 0 0; }
@media (max-width:900px) { .split { flex-direction:column; } #detail { flex:1 1 auto; width:100%; max-width:none; position:static; } }
#spinner { color:var(--text-dim); padding:24px; text-align:center; }
</style></head>
<body>
<main class="webux-page">
  <h2>📈 Watcher</h2>
  <div class="row">
    <label class="dim">Profile:</label>
    <input id="profile" placeholder="(active)" style="width:120px;">
    <label class="dim">Currency:</label>
    <select id="currency"><option value="USD" selected>USD</option><option value="EUR">EUR</option></select>
    <button id="refresh">🔄 Refresh</button>
    <span class="dim" id="generated"></span>
  </div>
  <div class="split">
    <div id="out"><div id="spinner">Loading…</div></div>
    <div id="detail"><div class="row"><strong id="detailTitle"></strong><span class="dim" id="detailMeta"></span><button id="detailGlobal" title="Back to global news" style="display:none;">⇤ All news</button></div><div id="detailChart"><div class="dim" id="detailStats"></div><canvas id="spark" width="640" height="160" style="width:100%;height:160px;"></canvas><h4 style="margin:12px 0 6px 0;">📰 News for <span id="detailNewsTitle"></span></h4></div><div class="news" id="detailNews" style="margin-top:0;"></div><div class="row" id="newsPager" style="display:none;"><button id="pgFirst" title="Back to start">⇤</button><button id="pgPrev" title="Previous 5">‹</button><span class="dim" id="pgInfo"></span><button id="pgNext" title="Next 5">›</button></div></div>
  </div>
</main>
<script>
const out = document.getElementById('out');
const detail = document.getElementById('detail');
let selectedId = null;
let lastVars = {};
let globalNews = [];
let newsList = [];
let newsPage = 0;
const PAGE_SIZE = 5;
function newsItem(n) {
  return `<a href="${esc(n.url || '#')}" target="_blank" rel="noopener"><div class="meta">${esc(n.published_at || '')} · ${esc(n.source || '')}</div>${esc(n.title || '')}</a>`;
}
function renderNewsPage() {
  const box = document.getElementById('detailNews');
  const pager = document.getElementById('newsPager');
  const total = newsList.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  newsPage = Math.min(Math.max(0, newsPage), pages - 1);
  const start = newsPage * PAGE_SIZE;
  const slice = newsList.slice(start, start + PAGE_SIZE);
  box.innerHTML = slice.length ? slice.map(newsItem).join('') : '<span class="dim">No news.</span>';
  pager.style.display = total > PAGE_SIZE ? 'flex' : 'none';
  document.getElementById('pgInfo').textContent = total ? `${start + 1}–${start + slice.length} of ${total}` : '';
  document.getElementById('pgFirst').disabled = newsPage === 0;
  document.getElementById('pgPrev').disabled = newsPage === 0;
  document.getElementById('pgNext').disabled = newsPage >= pages - 1;
}
function showGlobalNews() {
  selectedId = null;
  out.querySelectorAll('.card.selected').forEach(c => c.classList.remove('selected'));
  document.getElementById('detailTitle').textContent = '📰 Latest news';
  document.getElementById('detailMeta').textContent = '';
  document.getElementById('detailGlobal').style.display = 'none';
  document.getElementById('detailChart').style.display = 'none';
  newsList = globalNews;
  newsPage = 0;
  renderNewsPage();
  detail.style.display = 'block';
}
function cardBody(r) {
  const alt = (r.secondary_value != null && r.secondary_unit) ? `<div class="dim">≈ ${esc(display(r.secondary_value, r.secondary_unit))}</div>` : '';
  if (r.error && r.value != null) {
    return `<div class="card-value">${esc(display(r.value, r.unit))}<span class="stale">STALE</span></div>${alt}<div class="err">WARNING: ${esc(r.error)}</div>`;
  } else if (r.error) {
    return `<div class="err">ERROR: ${esc(r.error)}</div>`;
  }
  return `<div class="card-value">${esc(display(r.value, r.unit))}${r.stale ? '<span class="stale">STALE</span>' : ''}</div>${alt}`;
}
function esc(s) { return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
function display(v, unit) {
  if (unit === 'percent') return String(v) + '%';
  const a = Math.abs(v);
  if (a >= 1e9) return (v/1e9).toFixed(2) + 'B ' + unit;
  if (a >= 1e6) return (v/1e6).toFixed(2) + 'M ' + unit;
  if (a >= 1e3) return (v/1e3).toFixed(2) + 'K ' + unit;
  return Number(v).toFixed(2) + ' ' + unit;
}
function fmtChange(r) {
  if (r.change_abs == null) return '<span class="dim">—</span>';
  const cls = r.change_abs >= 0 ? 'up' : 'down';
  const sign = r.change_abs >= 0 ? '+' : '';
  return `<span class="${cls}">${sign}${r.change_abs} (${sign}${r.change_pct.toFixed(2)}%)</span>`;
}
async function load(force) {
  detail.style.display = 'none';
  selectedId = null;
  lastVars = {};
  out.innerHTML = '<div id="spinner">Loading…</div>';
  const profile = document.getElementById('profile').value.trim();
  const currency = document.getElementById('currency').value;
  const params = new URLSearchParams({last: '50'});
  params.set('main_currency', currency === 'EUR' ? 'EUR' : 'USD');
  if (force) params.set('refresh', '1');
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
  const vars = data.variables || [];
  vars.forEach(r => { lastVars[r.id] = r; });
  out.innerHTML = vars.length ? `<div class="cards-grid">` + vars.map(r => {
    return `<article class="card" data-id="${esc(r.id)}" tabindex="0" role="button" aria-label="${esc(r.id)} ${esc(r.label || '')}"><div class="card-head"><span class="card-id">${r.icon ? `<span class="card-icon">${esc(r.icon)}</span>` : ''}${esc(r.id)}</span><span class="dim">${esc(r.source || '')}</span></div><div class="card-label dim">${esc(r.label || '')}</div>${cardBody(r)}<div class="card-foot"><span>${fmtChange(r)}</span><span class="dim">${esc(r.as_of || '—')}</span></div></article>`;
  }).join('') + `</div>` : '<span class="dim">No variables.</span>';
  out.querySelectorAll('.card').forEach(card => {
    const pick = () => { if (card.dataset.id === selectedId) showGlobalNews(); else selectVariable(card.dataset.id, profile); };
    card.onclick = pick;
    card.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } };
  });
  globalNews = data.news || [];
  showGlobalNews();
}
async function selectVariable(id, profile) {
  selectedId = id;
  out.querySelectorAll('.card').forEach(c => c.classList.toggle('selected', c.dataset.id === id));
  const meta = lastVars[id] || {};
  document.getElementById('detailTitle').textContent = (meta.icon ? meta.icon + ' ' : '') + id;
  document.getElementById('detailMeta').textContent = [meta.label, meta.as_of ? ('as of ' + meta.as_of) : null, meta.source].filter(Boolean).join(' · ') || 'loading…';
  document.getElementById('detailGlobal').style.display = '';
  document.getElementById('detailStats').textContent = 'loading…';
  document.getElementById('detailChart').style.display = 'block';
  detail.style.display = 'block';
  try { detail.scrollIntoView({behavior: 'smooth', block: 'nearest'}); } catch (e) {}
  loadDetailNews(id, profile);
  const params = new URLSearchParams({variable: id, since: '90d'});
  if (profile) params.set('profile', profile);
  let data;
  try {
    const r = await fetch('/api/watcher/history?' + params.toString());
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
  } catch (e) {
    document.getElementById('detailStats').textContent = 'failed: ' + e.message;
    return;
  }
  const obs = (data.observations || []).filter(o => o.value != null);
  if (!obs.length) { document.getElementById('detailStats').textContent = 'no data'; return; }
  const vals = obs.map(o => o.value);
  document.getElementById('detailStats').textContent =
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
async function loadDetailNews(id, profile) {
  document.getElementById('detailNewsTitle').textContent = id;
  newsList = [];
  newsPage = 0;
  document.getElementById('detailNews').innerHTML = '<span class="dim">Loading news…</span>';
  document.getElementById('newsPager').style.display = 'none';
  const params = new URLSearchParams({variable: id, limit: '50'});
  if (profile) params.set('profile', profile);
  try {
    const r = await fetch('/api/watcher/news?' + params.toString());
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
    newsList = data.news || [];
    newsPage = 0;
    renderNewsPage();
  } catch (e) {
    document.getElementById('detailNews').innerHTML = `<span class="err">News failed: ${esc(e.message)}</span>`;
  }
}
document.getElementById('refresh').onclick = () => load(true);
document.getElementById('detailGlobal').onclick = () => showGlobalNews();
try {
  const savedCur = localStorage.getItem('watcher-currency');
  if (savedCur === 'EUR' || savedCur === 'USD') document.getElementById('currency').value = savedCur;
} catch (e) {}
document.getElementById('currency').onchange = (e) => {
  try { localStorage.setItem('watcher-currency', e.target.value); } catch (err) {}
  load(false);
};
document.getElementById('pgFirst').onclick = () => { newsPage = 0; renderNewsPage(); };
document.getElementById('pgPrev').onclick = () => { newsPage = Math.max(0, newsPage - 1); renderNewsPage(); };
document.getElementById('pgNext').onclick = () => { newsPage = newsPage + 1; renderNewsPage(); };
load(false);
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
