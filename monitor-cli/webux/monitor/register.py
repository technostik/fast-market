from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Query

from common.core.paths import get_tool_data_dir
from common.webux.base import WebuxPluginManifest

router = APIRouter()
_CLI_ROOT = Path(__file__).resolve().parents[2]


def _get_monitor_storage_class():
    """Load MonitorStorage from monitor-cli, avoiding cross-tool `core.*` collisions."""
    saved_core_modules = {
        name: module
        for name, module in list(sys.modules.items())
        if name == "core" or name.startswith("core.")
    }
    for name in saved_core_modules:
        sys.modules.pop(name, None)

    sys.path.insert(0, str(_CLI_ROOT))
    try:
        storage_module = importlib.import_module("core.storage")
        return storage_module.MonitorStorage
    finally:
        sys.path.pop(0)
        for name in list(sys.modules):
            if name == "core" or name.startswith("core."):
                sys.modules.pop(name, None)
        sys.modules.update(saved_core_modules)


def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    now = datetime.now()
    if since.endswith("d"):
        return now - timedelta(days=int(since[:-1]))
    if since.endswith("h"):
        return now - timedelta(hours=int(since[:-1]))
    if since.endswith("m"):
        return now - timedelta(minutes=int(since[:-1]))
    return datetime.fromisoformat(since)


@router.get("/logs")
def logs(
    since: str | None = Query(None),
    rule_id: str | None = Query(None),
    source_id: str | None = Query(None),
    limit: int = Query(100, le=500),
    mismatch: bool = Query(False),
) -> list[dict]:
    MonitorStorage = _get_monitor_storage_class()

    storage = MonitorStorage(get_tool_data_dir("monitor") / "monitor.db")
    since_dt = _parse_since(since)

    if mismatch:
        rows = storage.get_rule_mismatch_logs(
            since=since_dt,
            rule_id=rule_id,
            source_id=source_id,
            limit=limit,
        )
        return [
            {
                "id": r.id,
                "rule_id": r.rule_id,
                "source_id": r.source_id,
                "item_title": r.item_title,
                "failed_conditions": r.failed_conditions,
                "evaluated_at": r.evaluated_at.isoformat(),
            }
            for r in rows
        ]

    rows = storage.get_trigger_logs_with_metadata(
        since=since_dt,
        rule_id=rule_id,
        source_id=source_id,
        limit=limit,
    )
    return [
        {
            "id": r.id,
            "rule_id": r.rule_id,
            "source_id": r.source_id,
            "action_id": r.action_id,
            "item_title": r.item_title,
            "triggered_at": r.triggered_at.isoformat(),
            "exit_code": r.exit_code,
            "output": r.output,
        }
        for r in rows
    ]


@router.get("/status")
def status() -> dict:
    MonitorStorage = _get_monitor_storage_class()

    storage = MonitorStorage(get_tool_data_dir("monitor") / "monitor.db")
    return {
        "statistics": storage.get_stats(),
        "sources": [s.id for s in storage.get_all_sources()],
        "rules": [r.id for r in storage.get_all_rules()],
        "actions": [a.id for a in storage.get_all_actions()],
    }


@router.get("/filters")
def filters() -> dict[str, list[str]]:
    MonitorStorage = _get_monitor_storage_class()

    storage = MonitorStorage(get_tool_data_dir("monitor") / "monitor.db")
    return {
        "rule_ids": [r.id for r in storage.get_all_rules()],
        "source_ids": [s.id for s in storage.get_all_sources()],
        "action_ids": [a.id for a in storage.get_all_actions()],
    }


_HTML = """<!doctype html>
<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Monitor</title>
<style>
:root { --bg:#1a1a2e; --surface:#16213e; --accent:#0f3460; --text:#eee; --text-dim:#9ca3af; --border:#334155; --success:#22c55e; --error:#ef4444; --warning:#f59e0b; }
body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }
input, button, select { padding:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:6px; }
button { cursor:pointer; }
button:hover { background:var(--accent); }
.row { display:flex; gap:8px; margin-bottom:10px; align-items:center; flex-wrap:wrap; }
pre { white-space:pre-wrap; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:10px; }
h2 { margin:0 0 12px 0; }

/* Card styles */
.card { background:var(--surface); border:1px solid var(--border); border-radius:8px; margin-bottom:10px; cursor:pointer; transition:all 0.2s; }
.card:hover { border-color:var(--accent); transform:translateY(-1px); box-shadow:0 2px 8px rgba(0,0,0,0.3); }
.card-header { padding:12px 16px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.card-header:hover { background:rgba(255,255,255,0.03); }
.status-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.status-dot.success { background:var(--success); box-shadow:0 0 6px var(--success); }
.status-dot.error { background:var(--error); box-shadow:0 0 6px var(--error); }
.status-dot.warning { background:var(--warning); box-shadow:0 0 6px var(--warning); }
.card-field { display:flex; align-items:center; gap:4px; font-size:13px; }
.card-field .label { color:var(--text-dim); }
.card-field .value { color:var(--text); font-weight:500; }
.card-title { flex:1 1 auto; font-weight:600; min-width:200px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.card-expand { color:var(--text-dim); font-size:18px; transition:transform 0.2s; }
.card.expanded .card-expand { transform:rotate(180deg); }
.card-content { max-height:0; overflow:hidden; transition:max-height 0.3s ease-out; }
.card.expanded .card-content { max-height:2000px; transition:max-height 0.5s ease-in; }
.card-body { padding:0 16px 16px 16px; border-top:1px solid var(--border); }
.card-body pre { margin-top:8px; background:var(--bg); border:none; font-size:12px; max-height:400px; overflow-y:auto; }
.badge { padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600; }
.badge.success { background:rgba(34,197,94,0.15); color:var(--success); }
.badge.error { background:rgba(239,68,68,0.15); color:var(--error); }
.badge.warning { background:rgba(245,158,11,0.15); color:var(--warning); }
.badge.info { background:rgba(15,52,96,0.3); color:#60a5fa; }

/* Status view */
.stats-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:16px; }
.stat-card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; text-align:center; }
.stat-value { font-size:28px; font-weight:700; margin:8px 0; }
.stat-label { color:var(--text-dim); font-size:12px; text-transform:uppercase; letter-spacing:0.05em; }
.filter-section { margin-bottom:12px; }
</style></head>
<body>
  <h2>👁 Monitor</h2>
  <div class="row">
    <input id="since" placeholder="since (e.g. 1d, 2h)" style="width:140px;">
    <select id="ruleFilter" style="width:140px;"><option value="">All Rules</option></select>
    <select id="sourceFilter" style="width:140px;"><option value="">All Sources</option></select>
    <button id="loadLogs">📋 Load Logs</button>
    <button id="loadStatus">📊 Status</button>
  </div>
  <div id="out"></div>
  <script>
  const out = document.getElementById('out');
  const sinceInput = document.getElementById('since');
  const ruleFilter = document.getElementById('ruleFilter');
  const sourceFilter = document.getElementById('sourceFilter');

  function formatRelativeTime(isoString) {
    const now = new Date();
    const date = new Date(isoString);
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return 'just now';
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return diffMin + 'm ago';
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return diffHr + 'h ago';
    const diffDay = Math.floor(diffHr / 24);
    return diffDay + 'd ago';
  }

  function getStatusInfo(exitCode) {
    if (exitCode === 0) return { cls: 'success', label: 'Success' };
    if (exitCode === null || exitCode === undefined) return { cls: 'warning', label: 'Pending' };
    return { cls: 'error', label: 'Failed' };
  }

  function renderCards(rows, type) {
    if (!rows || rows.length === 0) return '<div style="text-align:center;padding:40px;color:var(--text-dim);">No entries found.</div>';
    return rows.map(r => {
      const triggeredAt = r.triggered_at || r.evaluated_at;
      const relativeTime = formatRelativeTime(triggeredAt);
      const status = type === 'mismatch' ? { cls: 'warning', label: 'Mismatch' } : getStatusInfo(r.exit_code);
      const title = r.item_title || '(no title)';
      let headerHtml = `
        <span class="status-dot ${status.cls}" title="${status.label}"></span>
        <span class="card-title" title="${title}">${title}</span>
        <span class="card-field"><span class="label">Rule:</span><span class="value badge info">${r.rule_id}</span></span>
        <span class="card-field"><span class="label">Source:</span><span class="value badge info">${r.source_id}</span></span>`;
      if (r.action_id) headerHtml += ` <span class="card-field"><span class="label">Action:</span><span class="value badge info">${r.action_id}</span></span>`;
      headerHtml += ` <span class="card-field"><span class="label">Time:</span><span class="value">${relativeTime}</span></span>`;
      headerHtml += ` <span class="badge ${status.cls}">${status.label}</span>`;
      headerHtml += ` <span class="card-expand">▼</span>`;

      let bodyHtml = '';
      if (type === 'mismatch') {
        bodyHtml = `<div class="card-body"><div><span class="label">Failed Conditions:</span><pre>${JSON.stringify(r.failed_conditions, null, 2)}</pre></div></div>`;
      } else {
        bodyHtml = `<div class="card-body">
          <div style="display:grid;grid-template-columns:auto 1fr;gap:6px;font-size:13px;">
            <span class="label">Exit Code:</span><span>${r.exit_code ?? 'N/A'}</span>
            <span class="label">ID:</span><span>${r.id}</span>
          </div>
          ${r.output ? `<pre>${r.output}</pre>` : ''}
        </div>`;
      }
      return `<div class="card" onclick="this.classList.toggle('expanded')"><div class="card-header">${headerHtml}</div><div class="card-content">${bodyHtml}</div></div>`;
    }).join('');
  }

  function renderStats(data) {
    const stats = data.statistics || {};
    const total = stats.total_triggers || 0;
    const success = stats.success_count || 0;
    const failed = stats.failed_count || 0;
    const successRate = total > 0 ? ((success / total) * 100).toFixed(1) : '0';
    return `
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-label">Total Triggers</div><div class="stat-value">${total}</div></div>
        <div class="stat-card"><div class="stat-label">Success</div><div class="stat-value" style="color:var(--success)">${success}</div></div>
        <div class="stat-card"><div class="stat-label">Failed</div><div class="stat-value" style="color:var(--error)">${failed}</div></div>
        <div class="stat-card"><div class="stat-label">Success Rate</div><div class="stat-value" style="color:${successRate >= 80 ? 'var(--success)' : successRate >= 50 ? 'var(--warning)' : 'var(--error)'}">${successRate}%</div></div>
      </div>
      <div class="filter-section">
        <div class="card-field"><span class="label">Sources:</span> ${(data.sources || []).map(s => `<span class="badge info">${s}</span>`).join(' ')}</div>
        <div class="card-field" style="margin-top:6px;"><span class="label">Rules:</span> ${(data.rules || []).map(r => `<span class="badge info">${r}</span>`).join(' ')}</div>
        <div class="card-field" style="margin-top:6px;"><span class="label">Actions:</span> ${(data.actions || []).map(a => `<span class="badge info">${a}</span>`).join(' ')}</div>
      </div>`;
  }

  async function loadFilters() {
    try {
      const r = await fetch('/api/monitor/filters');
      const data = await r.json();
      data.rule_ids?.forEach(id => { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; ruleFilter.appendChild(opt); });
      data.source_ids?.forEach(id => { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; sourceFilter.appendChild(opt); });
    } catch(e) { console.error('Failed to load filters:', e); }
  }

  document.getElementById('loadLogs').onclick = async () => {
    const since = sinceInput.value.trim();
    const rule = ruleFilter.value;
    const source = sourceFilter.value;
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    if (rule) params.set('rule_id', rule);
    if (source) params.set('source_id', source);
    const q = params.toString() ? '?' + params.toString() : '';
    const r = await fetch('/api/monitor/logs' + q);
    const data = await r.json();
    // Detect mismatch logs by checking first item
    const type = data.length > 0 && data[0].failed_conditions ? 'mismatch' : 'trigger';
    out.innerHTML = renderCards(data, type);
  };

  document.getElementById('loadStatus').onclick = async () => {
    const r = await fetch('/api/monitor/status');
    const data = await r.json();
    out.innerHTML = renderStats(data);
  };

  // Load filters on startup
  loadFilters();
  </script>
</body></html>
"""


def register(config: dict) -> WebuxPluginManifest:
    del config
    return WebuxPluginManifest(
        name="monitor",
        tab_label="Monitor",
        tab_icon="👁",
        api_router=router,
        frontend_html=_HTML,
        order=20,
        lazy=True,
    )
