from __future__ import annotations

from common.webux.base import WebuxPluginManifest
from webux.fileviewer.plugin import router


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
    .filters { padding:10px; border-bottom: 1px solid var(--border); display:flex; gap:6px; flex-direction:column; }
    .filters input { width:100%; box-sizing:border-box; }
    .section button { width:100%; text-align:left; padding:10px 12px; background:none; border:none; color:var(--text); cursor:pointer; }
    .section button:hover { background:var(--accent); }
    .tree { padding:8px 8px 12px 8px; display:none; }
    .node { margin-left: 10px; }
    .file { cursor:pointer; color:var(--text-dim); padding:2px 4px; border-radius:4px; }
    .file:hover { color:var(--text); background: #26395f; }
    .file.active { background:var(--accent); color:var(--text); }
    .dir { color:var(--warning); margin: 4px 0; cursor:pointer; user-select:none; }
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
  { key: 'workdir_root', label: '🗂 workdir_root (common/config.yaml)' }
];

let currentFile = null;
let editor = null;
let activeElement = null;
let currentSearchQuery = '';

const defaultExtensions = ['yaml', 'yml', 'json', 'txt', 'sh', 'md'];

function getActiveExtensions() {
  const showBak = document.getElementById('showBak').checked;
  if (showBak) return null;
  const raw = document.getElementById('extFilter').value || '';
  const parts = raw.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  if (!parts.length) return new Set(defaultExtensions);
  return new Set(parts);
}

function applyFileFilter(node, extensions) {
  if (!extensions || extensions.size === 0) return node;

  if (node.type === 'file') {
    const lowerName = node.name.toLowerCase();
    if (lowerName.includes('.bak')) return null;
    const ext = (node.name.split('.').pop() || '').toLowerCase();
    if (!node.name.includes('.')) return null;
    return extensions.has(ext) ? node : null;
  }

  const filteredChildren = (node.children || [])
    .map(child => applyFileFilter(child, extensions))
    .filter(Boolean);

  return { ...node, children: filteredChildren };
}

function escapeHtml(text) {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function setStatus(msg, color = 'var(--success)') {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = color;
  setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 2600);
}

function renderNode(node, container, expanded=false) {
  const wrap = document.createElement('div');
  wrap.className = 'node';

  if (node.type === 'dir') {
    const title = document.createElement('div');
    title.className = 'dir';
    const toggle = document.createElement('span');
    toggle.textContent = expanded ? '▼' : '▶';
    toggle.style.marginRight = '6px';
    const label = document.createElement('span');
    label.textContent = `📂 ${node.name}`;
    title.appendChild(toggle);
    title.appendChild(label);

    const childrenWrap = document.createElement('div');
    childrenWrap.style.display = expanded ? 'block' : 'none';
    (node.children || []).forEach(child => renderNode(child, childrenWrap));

    title.onclick = () => {
      const open = childrenWrap.style.display === 'block';
      childrenWrap.style.display = open ? 'none' : 'block';
      toggle.textContent = open ? '▶' : '▼';
    };

    wrap.appendChild(title);
    wrap.appendChild(childrenWrap);
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
  
  if (currentSearchQuery) {
    const cursor = editor.getSearchCursor(currentSearchQuery);
    const match = cursor.findNext();
    if (match) {
      editor.setSelection(cursor.from(), cursor.to());
      editor.scrollIntoView({ from: cursor.from(), to: cursor.to() });
      editor.focus();
    }
  }
  
  if (activeElement) activeElement.classList.remove('active');
  el.classList.add('active');
  activeElement = el;
}

async function loadSection(rootKey, treeContainer) {
  treeContainer.innerHTML = '<div class="node">Loading...</div>';
  
  const searchQuery = document.getElementById('searchQuery').value.trim();
  let url, tree;
  
  if (searchQuery && searchQuery.length >= 2) {
    url = `/api/fileviewer/search?root=${rootKey}&query=${encodeURIComponent(searchQuery)}`;
    currentSearchQuery = searchQuery;
  } else {
    url = `/api/fileviewer/tree?root=${rootKey}`;
    currentSearchQuery = '';
  }
  
  const resp = await fetch(url);
  if (!resp.ok) {
    treeContainer.innerHTML = '<div class="node">Unavailable</div>';
    return;
  }
  tree = await resp.json();
  const extensions = getActiveExtensions();
  const filteredTree = applyFileFilter(tree, extensions) || { ...tree, children: [] };

  treeContainer.innerHTML = '';
  if (filteredTree.children) {
    filteredTree.children.forEach(child => renderNode(child, treeContainer, true));
    return;
  }
  renderNode(filteredTree, treeContainer, true);
}

function initSidebar() {
  const left = document.getElementById('left');

  const filters = document.createElement('div');
  filters.className = 'filters';
  filters.innerHTML = '<label style="font-size:12px;color:var(--text-dim);">Visible extensions (comma-separated)</label><input id="extFilter" value="' + defaultExtensions.join(', ') + '" /><div style="display:flex;gap:6px;align-items:center;margin-top:6px;"><label style="font-size:12px;display:flex;align-items:center;gap:4px;"><input type="checkbox" id="showBak" /> Show .bak files</label><button id="applyFilter">Apply</button></div><div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);"><label style="font-size:12px;color:var(--text-dim);">Search in file contents</label><div style="display:flex;gap:6px;margin-top:4px;"><input id="searchQuery" placeholder="Type to search..." style="flex:1;" /><button id="doSearch">Search</button></div></div>';
  left.appendChild(filters);

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

  document.getElementById('applyFilter').onclick = async () => {
    for (const sectionEl of document.querySelectorAll('.section')) {
      const btn = sectionEl.querySelector('button');
      const tree = sectionEl.querySelector('.tree');
      if (tree.style.display === 'block') {
        const sectionDef = sections.find(s => s.label === btn.textContent);
        if (sectionDef) {
          await loadSection(sectionDef.key, tree);
        }
      }
    }
  };
  
  document.getElementById('doSearch').onclick = async () => {
    const query = document.getElementById('searchQuery').value.trim();
    if (query && query.length < 2) {
      setStatus('Search requires at least 2 characters', 'var(--warning)');
      return;
    }
    for (const sectionEl of document.querySelectorAll('.section')) {
      const btn = sectionEl.querySelector('button');
      const tree = sectionEl.querySelector('.tree');
      if (tree.style.display === 'block') {
        const sectionDef = sections.find(s => s.label === btn.textContent);
        if (sectionDef) {
          await loadSection(sectionDef.key, tree);
        }
      }
    }
    if (query) {
      setStatus('Search applied - files filtered by content');
    }
  };
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


def register(config: dict) -> WebuxPluginManifest:
    del config
    return WebuxPluginManifest(
        name="fileviewer",
        tab_label="Files",
        tab_icon="📁",
        api_router=router,
        frontend_html=_FILEVIEWER_HTML,
        order=30,
        lazy=True,
    )
