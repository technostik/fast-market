from __future__ import annotations

from plugins.base import PluginManifest
from plugins.yt_poster.plugin import router


_YT_POSTER_HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Webux YT Poster</title>
  <style>
    :root {
      --bg: #1a1a2e;
      --bg-secondary: #16213e;
      --text: #eee;
      --text-dim: #888;
      --accent: #0f3460;
      --success: #4ade80;
      --error: #f87171;
      --warning: #fbbf24;
      --border: #333;
    }
    body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
    .topbar { display:flex; gap:8px; align-items:center; margin-bottom:12px; }
    input, button { padding:8px 10px; border:1px solid var(--border); background:var(--bg-secondary); color:var(--text); border-radius:6px; }
    input { flex:1; }
    button { cursor:pointer; }
    button:hover { background:var(--accent); }
    .error { color:var(--error); min-height:20px; margin-bottom:6px; }
    .table-wrap { display:none; border:1px solid var(--border); border-radius:8px; overflow:auto; }
    table { border-collapse:collapse; width:100%; min-width:980px; }
    th, td { border-bottom:1px solid var(--border); padding:8px; vertical-align:top; font-size:13px; }
    th { background:var(--bg-secondary); position:sticky; top:0; }
    .clickable { cursor:pointer; color:#9ecbff; }
    .controls { display:none; margin:10px 0; gap:8px; }
    .footer { display:none; margin-top:12px; }
    .spinner { display:none; margin-top:12px; }
    .output { margin-top:10px; display:none; }
    pre { background:#0f172a; border:1px solid var(--border); border-radius:8px; padding:10px; overflow:auto; white-space:pre-wrap; }
    .badge { display:inline-block; border:1px solid var(--border); border-radius:999px; padding:1px 6px; font-size:11px; margin-right:4px; color:var(--text-dim); }
    .modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.65); align-items:center; justify-content:center; }
    .modal { width:min(920px,90vw); max-height:80vh; overflow:auto; background:var(--bg-secondary); border:1px solid var(--border); border-radius:8px; padding:14px; }
  </style>
</head>
<body>
  <div class=\"topbar\">
    <input id=\"fileInput\" placeholder=\"relative path from workdir\" />
    <button id=\"loadBtn\">Load</button>
  </div>
  <div id=\"error\" class=\"error\"></div>

  <div id=\"controls\" class=\"controls\">
    <button id=\"selectAll\">Select all</button>
    <button id=\"deselectAll\">Deselect all</button>
  </div>

  <div id=\"tableWrap\" class=\"table-wrap\">
    <table>
      <thead>
        <tr>
          <th>#</th><th>☑</th><th>Video</th><th>Author</th><th>Original Comment</th><th>Generated Reply</th><th>Like count</th>
        </tr>
      </thead>
      <tbody id=\"tbody\"></tbody>
    </table>
  </div>

  <div id=\"footer\" class=\"footer\">
    <button id=\"postBtn\">📤 Post selected (0)</button>
  </div>
  <div id=\"spinner\" class=\"spinner\">Posting... (this may take a while)</div>
  <div id=\"output\" class=\"output\">
    <div id=\"exitCode\"></div>
    <pre id=\"log\"></pre>
  </div>

  <div id=\"modalOverlay\" class=\"modal-overlay\">
    <div class=\"modal\"><pre id=\"modalText\"></pre></div>
  </div>

<script>
let rows = [];

const fileInput = document.getElementById('fileInput');
const loadBtn = document.getElementById('loadBtn');
const errorEl = document.getElementById('error');
const controls = document.getElementById('controls');
const tableWrap = document.getElementById('tableWrap');
const tbody = document.getElementById('tbody');
const footer = document.getElementById('footer');
const postBtn = document.getElementById('postBtn');
const selectAllBtn = document.getElementById('selectAll');
const deselectAllBtn = document.getElementById('deselectAll');
const spinner = document.getElementById('spinner');
const output = document.getElementById('output');
const exitCode = document.getElementById('exitCode');
const logEl = document.getElementById('log');
const modalOverlay = document.getElementById('modalOverlay');
const modalText = document.getElementById('modalText');

function trunc(v, n=100) { if (!v) return '—'; return v.length > n ? v.slice(0,n) + '…' : v; }
function esc(v='') { return String(v).replaceAll('&', '&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
function selectedCount(){ return rows.filter(r => r.selected).length; }
function updatePostLabel(){ postBtn.textContent = `📤 Post selected (${selectedCount()})`; }

function showModal(text){ modalText.textContent = text || ''; modalOverlay.style.display = 'flex'; }
modalOverlay.addEventListener('click', (e)=>{ if (e.target === modalOverlay) modalOverlay.style.display='none'; });
document.addEventListener('keydown', (e)=>{ if (e.key === 'Escape') modalOverlay.style.display='none'; });

function renderTable(){
  tbody.innerHTML = rows.map((row, i) => {
    const oc = row.original_comment || {};
    const stats = [
      oc.view_count != null ? `<span class=\"badge\">views: ${esc(oc.view_count)}</span>` : '',
      oc.like_count != null ? `<span class=\"badge\">likes: ${esc(oc.like_count)}</span>` : '',
      oc.comment_count != null ? `<span class=\"badge\">comments: ${esc(oc.comment_count)}</span>` : ''
    ].join('');
    const title = oc.video_title || trunc(row.video_url || '', 40);
    return `<tr>
      <td>${i}</td>
      <td><input type=\"checkbox\" data-i=\"${i}\" ${row.selected ? 'checked' : ''}></td>
      <td><a href=\"${esc(row.video_url || '#')}\" target=\"_blank\">${esc(title)}</a><div>${stats}</div></td>
      <td>${esc(oc.author || '—')}</td>
      <td><span class=\"clickable\" data-full=\"orig-${i}\">${esc(trunc(oc.text || oc.comment || ''))}</span></td>
      <td><span class=\"clickable\" data-full=\"reply-${i}\">${esc(trunc(row.reply || row.generated_reply || ''))}</span></td>
      <td>${oc.like_count != null ? esc(oc.like_count) : '—'}</td>
    </tr>`;
  }).join('');

  tbody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      const i = Number(cb.dataset.i);
      rows[i].selected = cb.checked;
      updatePostLabel();
    });
  });

  tbody.querySelectorAll('[data-full]').forEach(el => {
    el.addEventListener('click', () => {
      const [kind, idxRaw] = el.dataset.full.split('-');
      const idx = Number(idxRaw);
      const row = rows[idx];
      const oc = row.original_comment || {};
      if (kind === 'orig') showModal(oc.text || oc.comment || '');
      if (kind === 'reply') showModal(row.reply || row.generated_reply || '');
    });
  });

  updatePostLabel();
}

async function loadFile(){
  errorEl.textContent = '';
  output.style.display = 'none';
  const file = fileInput.value.trim();
  if (!file) { errorEl.textContent = 'Please enter a file path.'; return; }
  const resp = await fetch(`/api/yt_poster/load?file=${encodeURIComponent(file)}`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Load failed' }));
    errorEl.textContent = err.detail || 'Load failed';
    return;
  }
  const data = await resp.json();
  const url = new URL(window.location.href);
  url.searchParams.set('file', file);
  window.history.replaceState({}, '', url);

  rows = data.map(item => ({ ...item, selected: true }));
  controls.style.display = 'flex';
  tableWrap.style.display = 'block';
  footer.style.display = 'block';
  renderTable();
}

async function postSelected(){
  const file = fileInput.value.trim();
  const indices = rows.map((r, i) => r.selected ? i : -1).filter(i => i >= 0);
  spinner.style.display = 'block';
  output.style.display = 'none';

  const resp = await fetch('/api/yt_poster/post', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file, indices }),
  });

  spinner.style.display = 'none';
  const body = await resp.json().catch(() => ({}));
  output.style.display = 'block';
  const code = body.exit_code ?? -1;
  exitCode.textContent = `Exit code: ${code}`;
  exitCode.style.color = code === 0 ? 'var(--success)' : 'var(--error)';
  logEl.textContent = body.output || '';
}

loadBtn.addEventListener('click', loadFile);
postBtn.addEventListener('click', postSelected);
selectAllBtn.addEventListener('click', () => { rows.forEach(r => r.selected = true); renderTable(); });
deselectAllBtn.addEventListener('click', () => { rows.forEach(r => r.selected = false); renderTable(); });

const params = new URLSearchParams(window.location.search);
const preset = params.get('file');
if (preset) fileInput.value = preset;
</script>
</body>
</html>
"""


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="yt_poster",
        tab_label="YT Poster",
        tab_icon="📤",
        api_router=router,
        frontend_html=_YT_POSTER_HTML,
    )
