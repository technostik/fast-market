from __future__ import annotations

from plugins.base import PluginManifest
from plugins.fileviewer.plugin import router


_FILEVIEWER_HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Webux Fileviewer</title>
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css\">
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css\">
  <script src=\"https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js\"></script>
  <script src=\"https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js\"></script>
  <script src=\"https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/yaml/yaml.min.js\"></script>
  <script src=\"https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/markdown/markdown.min.js\"></script>
  <script src=\"https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/shell/shell.min.js\"></script>
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
    body { margin:0; font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:var(--bg); color:var(--text); }
    .layout { display:flex; height: calc(100vh - 60px); }
    .left { width: 280px; border-right: 1px solid var(--border); overflow:auto; background:var(--bg-secondary); }
    .right { flex:1; display:flex; flex-direction:column; min-width:0; }
    .section { border-bottom: 1px solid var(--border); }
    .section button { width:100%; text-align:left; padding:10px 12px; background:none; border:none; color:var(--text); cursor:pointer; }
    .section button:hover { background:var(--accent); }
    .tree { padding:8px 8px 12px 8px; display:none; }
    .node { margin-left: 10px; }
    .file { cursor:pointer; color:var(--text-dim); padding:2px 4px; border-radius:4px; }
    .file:hover { color:var(--text); background: #26395f; }
    .file.active { background:var(--accent); color:var(--text); }
    .dir { color:var(--warning); margin: 4px 0; }
    .toolbar { display:flex; gap:8px; align-items:center; padding:10px; border-bottom:1px solid var(--border); background:var(--bg-secondary); }
    .toolbar button { padding:8px 12px; border:1px solid var(--border); background:var(--bg); color:var(--text); border-radius:4px; cursor:pointer; }
    .toolbar button:hover { background:var(--accent); }
    .path { color:var(--text-dim); font-family:monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .status { margin-left:auto; font-size:12px; color:var(--success); }
    .editor-wrap { flex:1; min-height:0; }
    .CodeMirror { height:100% !important; font-size:14px; }
  </style>
</head>
<body>
  <div class=\"layout\">
    <aside class=\"left\" id=\"left\"></aside>
    <section class=\"right\">
      <div class=\"toolbar\">
        <button id=\"save\">Save</button>
        <button id=\"undo\">Undo</button>
        <span class=\"path\" id=\"currentPath\">No file selected</span>
        <span class=\"status\" id=\"status\"></span>
      </div>
      <div class=\"editor-wrap\"><textarea id=\"editor\"></textarea></div>
    </section>
  </div>

<script>
const sections = [
  { key: 'config', label: '⚙ Config (~/.config/fast-market)' },
  { key: 'data', label: '💾 Data (~/.local/share/fast-market)' },
  { key: 'workdir', label: '🗂 Workdir' }
];

let currentFile = null;
let editor = null;
let activeElement = null;

function escapeHtml(text) {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function setStatus(msg, color = 'var(--success)') {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = color;
  setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 2600);
}

function renderNode(node, container) {
  const wrap = document.createElement('div');
  wrap.className = 'node';

  if (node.type === 'dir') {
    const title = document.createElement('div');
    title.className = 'dir';
    title.textContent = `📂 ${node.name}`;
    wrap.appendChild(title);
    (node.children || []).forEach(child => renderNode(child, wrap));
  } else {
    const file = document.createElement('div');
    file.className = 'file';
    file.textContent = `📄 ${node.name}`;
    file.onclick = () => openFile(node.path, file);
    wrap.appendChild(file);
  }

  container.appendChild(wrap);
}

async function openFile(path, el) {
  const resp = await fetch(`/api/fileviewer/file?path=${encodeURIComponent(path)}`);
  if (!resp.ok) {
    setStatus('Failed to load file', 'var(--error)');
    return;
  }
  const data = await resp.json();
  currentFile = path;
  document.getElementById('currentPath').textContent = path;
  editor.setValue(data.content);
  editor.setOption('mode', data.language === 'json' ? 'javascript' : data.language);
  if (activeElement) activeElement.classList.remove('active');
  el.classList.add('active');
  activeElement = el;
}

async function loadSection(rootKey, treeContainer) {
  treeContainer.innerHTML = '<div class="node">Loading...</div>';
  const resp = await fetch(`/api/fileviewer/tree?root=${rootKey}`);
  if (!resp.ok) {
    treeContainer.innerHTML = '<div class="node">Unavailable</div>';
    return;
  }
  const tree = await resp.json();
  treeContainer.innerHTML = '';
  renderNode(tree, treeContainer);
}

function initSidebar() {
  const left = document.getElementById('left');
  sections.forEach(section => {
    const container = document.createElement('div');
    container.className = 'section';
    const btn = document.createElement('button');
    btn.textContent = section.label;
    const tree = document.createElement('div');
    tree.className = 'tree';

    let loaded = false;
    btn.onclick = async () => {
      const open = tree.style.display === 'block';
      tree.style.display = open ? 'none' : 'block';
      if (!open && !loaded) {
        loaded = true;
        await loadSection(section.key, tree);
      }
    };

    container.appendChild(btn);
    container.appendChild(tree);
    left.appendChild(container);
  });
}

async function saveCurrent() {
  if (!currentFile) return;
  const resp = await fetch(`/api/fileviewer/file?path=${encodeURIComponent(currentFile)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: editor.getValue() }),
  });
  if (!resp.ok) {
    setStatus('Save failed', 'var(--error)');
    return;
  }
  const data = await resp.json();
  const backupName = (data.backup || '').split('/').pop();
  setStatus(`✓ Saved (backup: ${backupName})`);
}

async function undoCurrent() {
  if (!currentFile) return;
  const resp = await fetch(`/api/fileviewer/undo?path=${encodeURIComponent(currentFile)}`, { method: 'POST' });
  if (!resp.ok) {
    setStatus('Undo failed', 'var(--error)');
    return;
  }
  await openFile(currentFile, activeElement);
  setStatus('✓ Restored from backup');
}

window.addEventListener('DOMContentLoaded', () => {
  editor = CodeMirror.fromTextArea(document.getElementById('editor'), {
    lineNumbers: true,
    mode: 'text',
    theme: 'dracula',
  });
  initSidebar();
  document.getElementById('save').onclick = saveCurrent;
  document.getElementById('undo').onclick = undoCurrent;
});
</script>
</body>
</html>
"""


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="fileviewer",
        tab_label="Files",
        tab_icon="📁",
        api_router=router,
        frontend_html=_FILEVIEWER_HTML,
    )
