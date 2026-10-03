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
.ranges { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }
.ranges button { padding:4px 10px; font-size:12px; }
.ranges button.active { background:var(--accent); border-color:var(--accent); }
#tvChart { width:100%; height:360px; margin:4px 0 8px 0; }
#nativeChart { width:100%; height:300px; margin:4px 0 8px 0; display:none; }
#ratioBox { font-size:12px; margin:6px 0; padding:8px 10px; border:1px solid var(--border); border-radius:6px; }
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
    <div id="detail"><div class="row"><strong id="detailTitle"></strong><span class="dim" id="detailMeta"></span><button id="detailGlobal" title="Back to global news" style="display:none;">⇤ All news</button></div><div id="detailChart"><div class="dim" id="detailStats"></div><div class="ranges" id="rangeRow"><button data-range="1D">1D</button><button data-range="1W">1W</button><button data-range="1M">1M</button><button data-range="1Y" class="active">1Y</button><button data-range="10Y">10Y</button><button data-range="MAX">MAX</button><span class="dim" id="tvSymbol"></span></div><div id="tvChart"></div><canvas id="nativeChart" width="640" height="300"></canvas><div id="ratioBox" style="display:none;"></div><div class="dim" id="detailSrc" style="font-size:11px;"></div><h4 style="margin:12px 0 6px 0;">📰 News for <span id="detailNewsTitle"></span></h4></div><div class="news" id="detailNews" style="margin-top:0;"></div><div class="row" id="newsPager" style="display:none;"><button id="pgFirst" title="Back to start">⇤</button><button id="pgPrev" title="Previous 5">‹</button><span class="dim" id="pgInfo"></span><button id="pgNext" title="Next 5">›</button></div></div>
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
  if (r.change_pct == null) return '<span class="dim">—</span>';
  const cls = r.change_pct >= 0 ? 'up' : 'down';
  const sign = r.change_pct >= 0 ? '+' : '';
  return `<span class="${cls}">${sign}${r.change_pct.toFixed(2)}%</span>`;
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
let tvRange = '1Y';
let tvLabel = '1Y';
const TV_INTERVAL = {'1D': '15', '1W': '60', '1M': 'D', '1Y': 'D', '10Y': 'W', 'MAX': 'W'};
const TV_RANGE = {'1D': '1D', '1W': '5D', '1M': '1M', '1Y': '12M', '10Y': 'ALL', 'MAX': 'ALL'};
const RANGE_DAYS = {'1D': 1, '1W': 7, '1M': 30, '1Y': 365, '10Y': 3650, 'MAX': Infinity};
// TVC bond yields and index tickers (NASDAQ:IXIC) are blocked in TradingView's
// free embed widgets ("only available on TradingView" = exchange licensing).
// No other free TV widget can show them, so these render from our own
// provider history (BdF/FRED/Yahoo — official daily fixings) instead.
const NATIVE_CHART = new Set(['fr_10y', 'us_10y', 'uk_10y', 'de_10y', 'nasdaq']);
// Monthly OECD series (no daily fixings): short ranges show the nearest points.
const MONTHLY = new Set(['uk_10y', 'de_10y']);
let nativeCache = {id: null, obs: [], profile: null};
function clearNative(msg) {
  const c = document.getElementById('nativeChart');
  c.getContext('2d').clearRect(0, 0, c.width, c.height);
  if (msg != null) document.getElementById('detailStats').textContent = msg;
}
const DEFAULT_TV = {fr_10y: 'TVC:FR10Y', us_10y: 'TVC:US10Y', uk_10y: 'TVC:GB10Y', de_10y: 'TVC:DE10Y', brent: 'TVC:UKOIL', wti: 'TVC:USOIL', napoleon: 'OANDA:XAUUSD', gold_spot: 'OANDA:XAUUSD', gold: 'OANDA:XAUUSD', nasdaq: 'NASDAQ:IXIC', bitcoin: 'BITSTAMP:BTCUSD', spacex: 'NASDAQ:SPCX', eurusd: 'OANDA:EURUSD'};
function tvSymbolFor(id) { return (lastVars[id] || {}).tradingview || DEFAULT_TV[id] || null; }
function eurValueOf(r) {
  if (!r || r.value == null) return null;
  if (String(r.unit || '').split('/')[0] === 'EUR') return r.value;
  if (r.secondary_unit && String(r.secondary_unit).split('/')[0] === 'EUR') return r.secondary_value;
  return null;
}
function renderRatio(id) {
  const box = document.getElementById('ratioBox');
  box.style.display = 'none';
  box.innerHTML = '';
  if (id !== 'napoleon' && id !== 'gold_spot') return;
  const nap = lastVars['napoleon'], gold = lastVars['gold_spot'];
  if (!nap || !gold || nap.value == null || gold.value == null) {
    box.style.display = 'block';
    box.innerHTML = '<span class="dim">Add both <b>napoleon</b> and <b>gold_spot</b> to the watchlist to see the coin premium (ratio).</span>';
    return;
  }
  const napEur = eurValueOf(nap), goldEurOz = eurValueOf(gold);
  if (napEur == null || goldEurOz == null || goldEurOz <= 0) return;
  const FINE_G = 5.806, OZ_G = 31.1035; // Napoléon 20F: 5.806g fine gold
  const melt = goldEurOz * FINE_G / OZ_G;
  const premium = napEur / melt - 1;
  box.style.display = 'block';
  box.innerHTML = `🪙 Napoléon <b>${esc(napEur.toFixed(2))} €</b> · melt <b>${esc(melt.toFixed(2))} €</b> (${FINE_G}g @ ${esc(goldEurOz.toFixed(0))} €/oz) · premium <b>${esc((premium*100).toFixed(1))}%</b> <span class="dim">ratio nap/melt = ${esc((napEur/melt).toFixed(3))}</span>`;
}
function loadChart(id) {
  document.querySelectorAll('#rangeRow button').forEach(b => b.classList.toggle('active', b.textContent === tvLabel));
  if (NATIVE_CHART.has(id)) loadNativeChart(id);
  else loadTradingView(id);
}
function sliceRange(obs, key) {
  const days = RANGE_DAYS[key] == null ? 365 : RANGE_DAYS[key];
  if (!isFinite(days)) return obs;
  const cut = new Date();
  cut.setDate(cut.getDate() - days);
  const iso = cut.toISOString().slice(0, 10);
  const out = obs.filter(o => o.date >= iso);
  return out.length ? out : obs.slice(-30); // daily fixings: 1D/1W would be empty
}
function drawNative(obs, key) {
  const c = document.getElementById('nativeChart'), ctx = c.getContext('2d');
  const W = c.width, H = c.height, P = 8, LP = 44;
  ctx.clearRect(0, 0, W, H);
  const vals = obs.map(o => o.value);
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  ctx.strokeStyle = '#334155'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(LP, H-P); ctx.lineTo(W-P, H-P); ctx.stroke();
  ctx.fillStyle = '#64748b'; ctx.font = '10px system-ui';
  [min, (min + max) / 2, max].forEach(v => {
    const y = P + (H - 2*P) * (1 - (v - min) / span);
    ctx.fillText(v.toFixed(2), 4, y + 3);
    ctx.strokeStyle = '#1e293b'; ctx.beginPath(); ctx.moveTo(LP, y); ctx.lineTo(W-P, y); ctx.stroke();
  });
  ctx.strokeStyle = '#4ade80'; ctx.lineWidth = 2; ctx.beginPath();
  obs.forEach((o, i) => {
    const x = LP + (W - LP - P) * (obs.length === 1 ? 1 : i / (obs.length - 1));
    const y = P + (H - 2*P) * (1 - (o.value - min) / span);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  if (obs.length === 1) {
    ctx.fillStyle = '#4ade80';
    ctx.beginPath(); ctx.arc(W - P, P + (H - 2*P) * (1 - (obs[0].value - min) / span), 3, 0, 7); ctx.fill();
  }
}
async function loadNativeChart(id) {
  const tv = document.getElementById('tvChart');
  const canvas = document.getElementById('nativeChart');
  const symSlot = document.getElementById('tvSymbol');
  const srcSlot = document.getElementById('detailSrc');
  tv.innerHTML = '';
  tv.style.display = 'none';
  canvas.style.display = 'block';
  clearNative('loading official history for ' + id + '…');
  symSlot.textContent = 'official history · ' + tvLabel;
  const profile = document.getElementById('profile').value.trim();
  let obs;
  if (nativeCache.id === id && nativeCache.profile === profile) {
    obs = nativeCache.obs;
  } else {
    const params = new URLSearchParams({variable: id, since: '30y'});
    if (profile) params.set('profile', profile);
    try {
      const r = await fetch('/api/watcher/history?' + params.toString());
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
      obs = (data.observations || []).filter(o => o.value != null);
    } catch (e) {
      if (selectedId !== id) return;
      clearNative('history for ' + id + ' failed to load: ' + e.message);
      return;
    }
    if (selectedId !== id) return; // superseded while fetching: never draw stale data
    nativeCache = {id, obs, profile};
  }
  if (selectedId !== id) return;
  const sliced = sliceRange(obs, tvRange);
  if (!sliced.length) {
    clearNative('no history yet for ' + id + ' — new points accumulate on each refresh');
    return;
  }
  const vals = sliced.map(o => o.value);
  document.getElementById('detailStats').textContent =
    `official ${tvLabel} · ${id}: ${sliced[0].date} → ${sliced[sliced.length-1].date} · ${sliced.length} pts · min ${Math.min(...vals).toFixed(2)} · max ${Math.max(...vals).toFixed(2)}`;
  srcSlot.textContent = MONTHLY.has(id)
    ? 'Native chart: official FRED/OECD monthly series (no daily fixings; short ranges show nearest points)'
    : (id === 'nasdaq'
      ? 'Native chart: official Yahoo daily history (TradingView blocks NASDAQ:IXIC in free embeds)'
      : 'Native chart: official daily fixing (TradingView blocks bond-yield TVC symbols in free embeds)');
  drawNative(sliced, tvRange);
}
function loadTradingView(id) {
  const box = document.getElementById('tvChart');
  const canvas = document.getElementById('nativeChart');
  canvas.style.display = 'none';
  box.style.display = 'block';
  const symSlot = document.getElementById('tvSymbol');
  const srcSlot = document.getElementById('detailSrc');
  const tv = tvSymbolFor(id);
  document.querySelectorAll('#rangeRow button').forEach(b => b.classList.toggle('active', b.textContent === tvLabel));
  box.innerHTML = '';
  if (!tv) {
    symSlot.textContent = '';
    srcSlot.textContent = 'No TradingView symbol mapped for this variable.';
    return;
  }
  symSlot.textContent = tv + ' · ' + tvLabel;
  const isCoin = (id === 'napoleon');
  srcSlot.textContent = isCoin
    ? 'Widget: spot gold proxy (Napoléon fixing has no listed symbol) · official fixing + premium below · source: TradingView'
    : 'Widget source: TradingView (' + tv + ') · official value above · range ' + tvLabel;
  const container = document.createElement('div');
  container.className = 'tradingview-widget-container';
  container.style.cssText = 'height:100%;width:100%';
  const widget = document.createElement('div');
  widget.className = 'tradingview-widget-container__widget';
  widget.style.cssText = 'height:calc(100% - 32px);width:100%';
  const copy = document.createElement('div');
  copy.className = 'tradingview-widget-copyright';
  copy.innerHTML = `<a href="https://www.tradingview.com/symbols/${esc(tv.replace(':', '-'))}/" rel="noopener nofollow" target="_blank"><span class="blue-text">${esc(tv)} chart</span></a><span class="trademark"> by TradingView</span>`;
  const script = document.createElement('script');
  script.type = 'text/javascript';
  script.async = true;
  script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.innerHTML = JSON.stringify({
    autosize: true, symbol: tv, interval: TV_INTERVAL[tvRange] || 'D', range: TV_RANGE[tvRange] || '12M',
    timezone: 'Europe/Paris', theme: 'dark', style: '3', locale: 'en',
    allow_symbol_change: false, hide_side_toolbar: true, support_host: 'https://www.tradingview.com'
  });
  container.appendChild(widget);
  container.appendChild(copy);
  container.appendChild(script);
  box.appendChild(container);
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
  renderRatio(id);
  if (NATIVE_CHART.has(id)) { loadChart(id); return; }
  loadTradingView(id);
  const params = new URLSearchParams({variable: id, since: '1y'});
  if (profile) params.set('profile', profile);
  let data;
  try {
    const r = await fetch('/api/watcher/history?' + params.toString());
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
  } catch (e) {
    if (selectedId !== id) return;
    document.getElementById('detailStats').textContent = 'official history failed: ' + e.message;
    return;
  }
  if (selectedId !== id) return;
  const obs = (data.observations || []).filter(o => o.value != null);
  if (!obs.length) { document.getElementById('detailStats').textContent = 'no official history (widget above still covers 1D–MAX)'; return; }
  const vals = obs.map(o => o.value);
  document.getElementById('detailStats').textContent =
    `official 1Y: ${obs[0].date} → ${obs[obs.length-1].date} · ${obs.length} pts · min ${Math.min(...vals).toFixed(2)} · max ${Math.max(...vals).toFixed(2)}`;
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
document.querySelectorAll('#rangeRow button').forEach(b => { b.onclick = () => { tvRange = b.dataset.range; tvLabel = b.textContent; if (selectedId) loadChart(selectedId); }; });
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
