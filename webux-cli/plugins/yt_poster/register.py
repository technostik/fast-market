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
      --link: #7dd3fc;
      --link-hover: #bae6fd;
    }
    body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
    .topbar { display:flex; gap:8px; align-items:center; margin-bottom:12px; }
    input, button { padding:8px 10px; border:1px solid var(--border); background:var(--bg-secondary); color:var(--text); border-radius:6px; }
    input { flex:1; }
    button { cursor:pointer; }
    button:hover { background:var(--accent); }
    .error { color:var(--error); min-height:20px; margin-bottom:6px; }
    .table-wrap { display:none; border:1px solid var(--border); border-radius:8px; overflow:auto; }
    table { border-collapse:collapse; width:100%; min-width:1100px; }
    th, td { border-bottom:1px solid var(--border); padding:8px; vertical-align:top; font-size:13px; }
    th { background:var(--bg-secondary); position:sticky; top:0; }
    .clickable { cursor:pointer; color:#9ecbff; }
    .controls { display:none; margin:10px 0; gap:8px; }
    .footer { display:none; margin-top:12px; }
    .spinner { display:none; margin-top:12px; }
    .output { margin-top:10px; display:none; }
    pre { background:#0f172a; border:1px solid var(--border); border-radius:8px; padding:10px; overflow:auto; white-space:pre-wrap; }
    .badge { display:inline-block; border:1px solid var(--border); border-radius:999px; padding:1px 6px; font-size:11px; margin-right:4px; color:var(--text-dim); }
    .video-link { color:var(--link); text-decoration:none; font-weight:500; }
    .video-link:hover { color:var(--link-hover); text-decoration:underline; }
    .channel-link { color:var(--link); text-decoration:none; font-size:12px; }
    .channel-link:hover { color:var(--link-hover); text-decoration:underline; }
    .stats { margin-top:4px; font-size:11px; color:var(--text-dim); }
    .stats span { margin-right:8px; }
    .modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.65); align-items:center; justify-content:center; }
    .modal { width:min(920px,90vw); max-height:80vh; overflow:auto; background:var(--bg-secondary); border:1px solid var(--border); border-radius:8px; padding:14px; }
    .modal-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
    .modal-header h3 { margin:0; font-size:16px; }
    .modal-close { background:none; border:none; font-size:20px; cursor:pointer; color:var(--text-dim); padding:4px 8px; }
    .modal-close:hover { color:var(--text); }
    .modal-body { margin-bottom:12px; }
    .modal-edit-area { width:100%; min-height:120px; padding:10px; border:1px solid var(--border); border-radius:6px; background:var(--bg); color:var(--text); font-family:inherit; font-size:13px; resize:vertical; }
    .modal-footer { display:flex; gap:8px; justify-content:flex-end; }
    .modal-footer button { padding:8px 16px; }
    .btn-save { background:var(--success); color:#000; border:none; font-weight:600; }
    .btn-save:hover { opacity:0.85; }
    .btn-cancel { background:var(--accent); color:var(--text); }
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
    <label style=\"display:flex;align-items:center;gap:6px;\">
      <input type=\"checkbox\" id=\"dryRun\"> Dry run
    </label>
  </div>

  <div id=\"tableWrap\" class=\"table-wrap\">
    <table>
      <thead>
        <tr>
          <th>#</th><th>☑</th><th>Video</th><th>Channel</th><th>Original Comment</th><th>Generated Reply</th>
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
    <div class=\"modal\">
      <div class=\"modal-header\">
        <h3 id=\"modalTitle\">Comment</h3>
        <button class=\"modal-close\" id=\"modalCloseBtn\">&times;</button>
      </div>
      <div class=\"modal-body\" id=\"modalBody\">
        <pre id=\"modalText\"></pre>
      </div>
      <div class=\"modal-footer\" id=\"modalFooter\" style=\"display:none;\">
        <button class=\"btn-cancel\" id=\"modalCancelBtn\">Cancel</button>
        <button class=\"btn-save\" id=\"modalSaveBtn\">Save</button>
      </div>
    </div>
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
const dryRunEl = document.getElementById('dryRun');
const spinner = document.getElementById('spinner');
const output = document.getElementById('output');
const exitCode = document.getElementById('exitCode');
const logEl = document.getElementById('log');
const modalOverlay = document.getElementById('modalOverlay');
const modalTitle = document.getElementById('modalTitle');
const modalText = document.getElementById('modalText');
const modalBody = document.getElementById('modalBody');
const modalFooter = document.getElementById('modalFooter');
const modalCloseBtn = document.getElementById('modalCloseBtn');
const modalCancelBtn = document.getElementById('modalCancelBtn');
const modalSaveBtn = document.getElementById('modalSaveBtn');

let editingRowIndex = -1;
let currentSourceFile = '';

function trunc(v, n=100) { if (!v) return '—'; return v.length > n ? v.slice(0,n) + '…' : v; }
function esc(v='') { return String(v).replaceAll('&', '&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
function selectedCount(){ return rows.filter(r => r.selected).length; }
function updatePostLabel(){ postBtn.textContent = `📤 Post selected (${selectedCount()})`; }

function formatRelativeDate(dateStr) {
  if (!dateStr) return '';
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now - date;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);
  const diffWeek = Math.floor(diffDay / 7);
  const diffMonth = Math.floor(diffDay / 30);
  const diffYear = Math.floor(diffDay / 365);

  if (diffSec < 60) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  if (diffWeek < 5) return `${diffWeek}w ago`;
  if (diffMonth < 12) return `${diffMonth}mo ago`;
  return `${diffYear}y ago`;
}

function formatNumber(n) {
  if (n == null) return '—';
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\\.0$/, '') + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\\.0$/, '') + 'K';
  return n.toString();
}

function showModal(text, editable=false, rowIndex=-1){
  editingRowIndex = rowIndex;
  if (editable && rowIndex >= 0) {
    modalTitle.textContent = 'Edit Reply';
    modalBody.innerHTML = '<textarea id=\"modalTextarea\" class=\"modal-edit-area\">' + esc(text || '') + '</textarea>';
    modalFooter.style.display = 'flex';
  } else {
    modalTitle.textContent = 'Comment';
    modalBody.innerHTML = '<pre id=\"modalText\"></pre>';
    document.getElementById('modalText').textContent = text || '';
    modalFooter.style.display = 'none';
  }
  modalOverlay.style.display = 'flex';
}

function closeModal(){
  modalOverlay.style.display = 'none';
  editingRowIndex = -1;
}

async function saveReply(){
  const textarea = document.getElementById('modalTextarea');
  if (!textarea || editingRowIndex < 0) return;
  const newText = textarea.value;
  rows[editingRowIndex].reply = newText;
  rows[editingRowIndex].generated_reply = newText;

  const resp = await fetch('/api/yt_poster/save_reply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file: currentSourceFile, index: editingRowIndex, reply: newText }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Save failed' }));
    errorEl.textContent = err.detail || 'Save failed';
  } else {
    errorEl.textContent = '';
  }
  closeModal();
  renderTable();
}
modalOverlay.addEventListener('click', (e)=>{ if (e.target === modalOverlay) closeModal(); });
document.addEventListener('keydown', (e)=>{ if (e.key === 'Escape') closeModal(); });
modalCloseBtn.addEventListener('click', closeModal);
modalCancelBtn.addEventListener('click', closeModal);
modalSaveBtn.addEventListener('click', saveReply);

function renderTable(){
  tbody.innerHTML = rows.map((row, i) => {
    const oc = row.original_comment || {};
    const title = oc.video_title || trunc(row.video_url || '', 40);
    const videoUrl = row.video_url || '#';
    const channelName = oc.channel_name || '—';
    const channelUrl = oc.channel_url || '#';
    const viewCount = oc.view_count != null ? formatNumber(oc.view_count) : '—';
    const likeCount = oc.like_count != null ? formatNumber(oc.like_count) : '—';
    const dateAge = oc.published_at ? formatRelativeDate(oc.published_at) : '';

    const stats = [];
    if (viewCount !== '—') stats.push(`<span>👁 ${viewCount}</span>`);
    if (likeCount !== '—') stats.push(`<span>❤️ ${likeCount}</span>`);
    if (dateAge) stats.push(`<span>📅 ${dateAge}</span>`);

    return `<tr>
      <td>${i}</td>
      <td><input type=\"checkbox\" data-i=\"${i}\" ${row.selected ? 'checked' : ''}></td>
      <td>
        <a href=\"${esc(videoUrl)}\" class=\"video-link\" target=\"_blank\">${esc(title)}</a>
        <div class=\"stats\">${stats.join('')}</div>
      </td>
      <td><a href=\"${esc(channelUrl)}\" class=\"channel-link\" target=\"_blank\">${esc(channelName)}</a></td>
      <td><span class=\"clickable\" data-full=\"orig-${i}\">${esc(trunc(oc.text || oc.comment || ''))}</span></td>
      <td>
        <span class=\"clickable\" data-full=\"reply-${i}\">${esc(trunc(row.reply || row.generated_reply || ''))}</span>
        <button class=\"edit-reply-btn\" data-i=\"${i}\" style=\"margin-left:6px;padding:2px 6px;font-size:11px;cursor:pointer;\">✏️</button>
      </td>
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

  tbody.querySelectorAll('.edit-reply-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.i);
      const row = rows[idx];
      const replyText = row.reply || row.generated_reply || '';
      showModal(replyText, true, idx);
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

  currentSourceFile = file;
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
    body: JSON.stringify({ file, indices, dry_run: dryRunEl.checked }),
  });

  spinner.style.display = 'none';
  const body = await resp.json().catch(() => ({}));
  output.style.display = 'block';
  const code = body.exit_code ?? -1;
  exitCode.textContent = `Exit code: ${code}`;
  exitCode.style.color = code === 0 ? 'var(--success)' : 'var(--error)';
  const reportPath = body.report ? `\nReport: ${body.report}` : '';
  const mode = body.dry_run ? '[dry-run] ' : '';
  logEl.textContent = `${mode}${body.output || ''}${reportPath}`;
}

loadBtn.addEventListener('click', loadFile);
postBtn.addEventListener('click', postSelected);
selectAllBtn.addEventListener('click', () => { rows.forEach(r => r.selected = true); renderTable(); });
deselectAllBtn.addEventListener('click', () => { rows.forEach(r => r.selected = false); renderTable(); });

const params = new URLSearchParams(window.location.search);
const preset = params.get('file') || 'replies.json';
if (preset) {
  fileInput.value = preset;
  loadFile();
}
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
