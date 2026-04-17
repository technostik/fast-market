from __future__ import annotations

from common.webux.base import WebuxPluginManifest
from webux.skill_runner.plugin import router

_SKILL_RUNNER_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Skill Runner</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/yaml/yaml.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/markdown/markdown.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/shell/shell.min.js"></script>
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
    .left { width: 300px; border-right: 1px solid var(--border); overflow:auto; background:var(--bg-secondary); display:flex; flex-direction:column; }
    .right { flex:1; display:flex; flex-direction:column; min-width:0; }
    .load-bar { padding:12px; border-bottom:1px solid var(--border); flex-shrink:0; }
    .section-label { font-size:11px; color:var(--text-dim); text-transform:uppercase; margin-bottom:6px; letter-spacing:0.5px; }
    .plan-list { max-height:200px; overflow:auto; margin-bottom:10px; border:1px solid var(--border); border-radius:4px; background:var(--bg); }
    .plan-item { padding:8px 10px; cursor:pointer; border-bottom:1px solid var(--border); font-size:13px; color:var(--text-dim); }
    .plan-item:last-child { border-bottom:none; }
    .plan-item:hover { background:var(--accent); color:var(--text); }
    .plan-item.selected { background:var(--accent); color:var(--text); }
    .plan-item .rel { font-size:11px; color:var(--text-dim); margin-left:8px; }
    .divider { text-align:center; color:var(--text-dim); font-size:11px; margin:8px 0; }
    .divider span { background:var(--bg-secondary); padding:0 8px; }
    .load-bar input { width:100%; box-sizing:border-box; padding:8px; border:1px solid var(--border); border-radius:4px; background:var(--bg); color:var(--text); margin-bottom:6px; }
    .load-bar .btn-row { display:flex; gap:6px; }
    .load-bar button { flex:1; padding:8px; border:1px solid var(--border); border-radius:4px; cursor:pointer; background:var(--bg); color:var(--text); }
    .load-bar button:hover { background:var(--accent); }
    .file-list { flex:1; overflow:auto; padding:8px; }
    .group { margin-bottom:8px; }
    .group-header { display:flex; align-items:center; gap:6px; padding:8px; background:var(--bg); border-radius:4px; cursor:pointer; user-select:none; }
    .group-header:hover { background:var(--accent); }
    .group-header .toggle { color:var(--text-dim); font-size:10px; }
    .group-files { padding-left:16px; display:none; }
    .group-files.open { display:block; }
    .file-item { padding:4px 8px; cursor:pointer; color:var(--text-dim); border-radius:4px; font-size:13px; }
    .file-item:hover { color:var(--text); background:#26395f; }
    .file-item.active { background:var(--accent); color:var(--text); }
    .empty-state { padding:20px; text-align:center; color:var(--text-dim); font-size:13px; }
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
  <div class="layout">
    <aside class="left">
      <div class="load-bar">
        <div class="section-label">Detected Plans</div>
        <div class="filter-row" style="display:flex;gap:6px;margin-bottom:6px;">
          <input type="text" id="patternInput" value="*.run.yaml" style="flex:1;" placeholder="Filter pattern..." />
          <button id="refreshPlans" style="padding:8px 12px;">⟳</button>
        </div>
        <div class="plan-list" id="planList">
          <div class="plan-item" style="color:var(--text-dim)">Loading...</div>
        </div>
        <div class="divider"><span>or enter URL</span></div>
        <input type="text" id="urlInput" placeholder="https://..." />
        <div class="btn-row">
          <button id="loadBtn">Load Plan</button>
          <button id="clearBtn">Clear</button>
        </div>
      </div>
      <div class="file-list" id="fileList">
        <div class="empty-state">Load a plan to see files</div>
      </div>
    </aside>
    <section class="right">
      <div class="toolbar">
        <button id="save">Save</button>
        <button id="undo">Undo</button>
        <span class="path" id="currentPath">No file selected</span>
        <span class="status" id="status"></span>
      </div>
      <div class="editor-wrap"><textarea id="editor"></textarea></div>
    </section>
  </div>

<script>
let currentFile = null;
let editor = null;
let activeElement = null;
let planContent = '';
let planPath = null;
let detectedPlans = [];

function escapeHtml(text) {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function setStatus(msg, color = 'var(--success)') {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = color;
  setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 2600);
}

async function openFile(path, el) {
  const resp = await fetch(`/api/skill_runner/file?path=${encodeURIComponent(path)}`);
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
  if (el) {
    el.classList.add('active');
    activeElement = el;
  }
}

function renderDetectedPlans() {
  const container = document.getElementById('planList');
  if (detectedPlans.length === 0) {
    container.innerHTML = '<div class="plan-item" style="color:var(--text-dim)">No plans found</div>';
    return;
  }
  container.innerHTML = '';
  detectedPlans.forEach((plan, idx) => {
    const item = document.createElement('div');
    item.className = 'plan-item';
    item.innerHTML = `${escapeHtml(plan.name)}<span class="rel">${escapeHtml(plan.relative)}</span>`;
    item.onclick = () => {
      document.querySelectorAll('.plan-item').forEach(el => el.classList.remove('selected'));
      item.classList.add('selected');
      document.getElementById('urlInput').value = plan.path;
      loadPlan();
    };
    container.appendChild(item);
  });
}

function renderFileList(skillsData, promptsData) {
  const container = document.getElementById('fileList');
  container.innerHTML = '';

  const runYAMLEl = document.createElement('div');
  runYAMLEl.className = 'group';
  const runPath = planPath || 'plan.yaml';
  runYAMLEl.innerHTML = `
    <div class="group-header" data-group="run-yaml">
      <span class="toggle">▶</span>
      <span>📄 Run YAML</span>
    </div>
    <div class="group-files open" id="run-yaml-files">
      <div class="file-item" data-path="${escapeHtml(runPath)}">${escapeHtml(runPath.split('/').pop())}</div>
    </div>
  `;
  runYAMLEl.querySelector('.group-header').onclick = () => {
    const files = runYAMLEl.querySelector('.group-files');
    const toggle = runYAMLEl.querySelector('.toggle');
    const isOpen = files.classList.toggle('open');
    toggle.textContent = isOpen ? '▼' : '▶';
  };
  runYAMLEl.querySelector('.file-item').onclick = (e) => {
    openFile(e.target.dataset.path, e.target);
  };
  container.appendChild(runYAMLEl);

  if (skillsData && skillsData.length > 0) {
    const skillsGroup = document.createElement('div');
    skillsGroup.className = 'group';
    skillsGroup.innerHTML = `
      <div class="group-header" data-group="skills">
        <span class="toggle">▶</span>
        <span>📂 Skills</span>
      </div>
      <div class="group-files" id="skills-files"></div>
    `;
    skillsGroup.querySelector('.group-header').onclick = () => {
      const files = skillsGroup.querySelector('.group-files');
      const toggle = skillsGroup.querySelector('.toggle');
      const isOpen = files.classList.toggle('open');
      toggle.textContent = isOpen ? '▼' : '▶';
    };
    const filesContainer = skillsGroup.querySelector('#skills-files');

    skillsData.forEach(skill => {
      const skillDiv = document.createElement('div');
      skillDiv.style.marginBottom = '8px';
      skillDiv.innerHTML = `
        <div class="group-header" data-group="skill-${skill.name}" style="padding:6px 8px; font-size:12px;">
          <span class="toggle">▶</span>
          <span>📂 ${escapeHtml(skill.name)}</span>
        </div>
        <div class="group-files" id="skill-files-${skill.name}" style="padding-left:12px;"></div>
      `;
      skillDiv.querySelector('.group-header').onclick = () => {
        const files = skillDiv.querySelector('.group-files');
        const toggle = skillDiv.querySelector('.toggle');
        const isOpen = files.classList.toggle('open');
        toggle.textContent = isOpen ? '▼' : '▶';
      };
      const skillFilesContainer = skillDiv.querySelector('.group-files');
      skill.files.forEach(f => {
        const fileItem = document.createElement('div');
        fileItem.className = 'file-item';
        fileItem.textContent = f.relative;
        fileItem.onclick = (e) => openFile(f.path, e.target);
        skillFilesContainer.appendChild(fileItem);
      });
      filesContainer.appendChild(skillDiv);
    });
    container.appendChild(skillsGroup);
  }

  if (promptsData && promptsData.length > 0) {
    const promptsGroup = document.createElement('div');
    promptsGroup.className = 'group';
    promptsGroup.innerHTML = `
      <div class="group-header" data-group="prompts">
        <span class="toggle">▶</span>
        <span>📂 Prompts</span>
      </div>
      <div class="group-files" id="prompts-files"></div>
    `;
    promptsGroup.querySelector('.group-header').onclick = () => {
      const files = promptsGroup.querySelector('.group-files');
      const toggle = promptsGroup.querySelector('.toggle');
      const isOpen = files.classList.toggle('open');
      toggle.textContent = isOpen ? '▼' : '▶';
    };
    const filesContainer = promptsGroup.querySelector('#prompts-files');
    promptsData.forEach(p => {
      const fileItem = document.createElement('div');
      fileItem.className = 'file-item';
      fileItem.textContent = p.name;
      fileItem.onclick = (e) => openFile(p.path, e.target);
      filesContainer.appendChild(fileItem);
    });
    container.appendChild(promptsGroup);
  }
}

async function loadPlan() {
  const input = document.getElementById('urlInput').value.trim();
  if (!input) {
    setStatus('Enter URL or file path', 'var(--warning)');
    return;
  }

  let url, path;
  if (input.startsWith('http://') || input.startsWith('https://')) {
    url = input;
    path = null;
  } else {
    url = null;
    path = input;
  }

  const params = new URLSearchParams();
  if (url) params.set('url', url);
  if (path) params.set('path', path);

  try {
    const resp = await fetch(`/api/skill_runner/load-plan?${params}`);
    if (!resp.ok) {
      const err = await resp.json();
      setStatus('Failed: ' + (err.detail || 'Unknown error'), 'var(--error)');
      return;
    }
    const data = await resp.json();
    planContent = data.content;
    planPath = data.path;
    currentFile = planPath;
    document.getElementById('currentPath').textContent = planPath;
    editor.setValue(planContent);
    editor.setOption('mode', 'yaml');

    const skillsResp = await fetch(`/api/skill_runner/skills-from-plan-path?path=${encodeURIComponent(planPath)}`);
    const skillsData = skillsResp.ok ? await skillsResp.json() : [];

    let promptsData = [];
    if (skillsData.length > 0) {
      const promptsResp = await fetch('/api/skill_runner/prompts-for-skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skills: skillsData }),
      });
      promptsData = promptsResp.ok ? await promptsResp.json() : [];
    }

    renderFileList(skillsData, promptsData);
    setStatus('Plan loaded');
  } catch (exc) {
    setStatus('Error: ' + exc.message, 'var(--error)');
  }
}

function clearPlan() {
  document.getElementById('urlInput').value = '';
  document.getElementById('fileList').innerHTML = '<div class="empty-state">Load a plan to see files</div>';
  document.getElementById('currentPath').textContent = 'No file selected';
  editor.setValue('');
  currentFile = null;
  planContent = '';
  planPath = null;
  document.querySelectorAll('.plan-item').forEach(el => el.classList.remove('selected'));
  if (activeElement) {
    activeElement.classList.remove('active');
    activeElement = null;
  }
  setStatus('Cleared');
}

async function saveCurrent() {
  if (!currentFile) return;
  const resp = await fetch(`/api/skill_runner/file?path=${encodeURIComponent(currentFile)}`, {
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
  const resp = await fetch(`/api/skill_runner/undo?path=${encodeURIComponent(currentFile)}`, { method: 'POST' });
  if (!resp.ok) {
    setStatus('Undo failed', 'var(--error)');
    return;
  }
  await openFile(currentFile, activeElement);
  setStatus('✓ Restored from backup');
}

async function loadDetectedPlans() {
  try {
    const pattern = document.getElementById('patternInput').value.trim() || '*.run.yaml';
    const resp = await fetch(`/api/skill_runner/plans?pattern=${encodeURIComponent(pattern)}`);
    if (resp.ok) {
      detectedPlans = await resp.json();
      renderDetectedPlans();
    }

    const namesResp = await fetch('/api/skill_runner/prompt-names');
    if (namesResp.ok) {
      const names = await namesResp.json();
      console.log('Available prompts:', names);
    }
  } catch (exc) {
    console.error('Failed to load plans:', exc);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  editor = CodeMirror.fromTextArea(document.getElementById('editor'), {
    lineNumbers: true,
    mode: 'yaml',
    theme: 'dracula',
  });
  document.getElementById('loadBtn').onclick = loadPlan;
  document.getElementById('clearBtn').onclick = clearPlan;
  document.getElementById('save').onclick = saveCurrent;
  document.getElementById('undo').onclick = undoCurrent;
  document.getElementById('refreshPlans').onclick = loadDetectedPlans;
  document.getElementById('urlInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadPlan();
  });
  document.getElementById('patternInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadDetectedPlans();
  });
  loadDetectedPlans();
});
</script>
</body>
</html>
"""


def register(config: dict) -> WebuxPluginManifest:
    del config
    return WebuxPluginManifest(
        name="skill_runner",
        tab_label="Plan Editor",
        tab_icon="▶",
        api_router=router,
        frontend_html=_SKILL_RUNNER_HTML,
        order=20,
        lazy=True,
    )
