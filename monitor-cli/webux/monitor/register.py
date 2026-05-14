from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException

from common.core.paths import get_tool_data_dir
from common.webux.base import WebuxPluginManifest

router = APIRouter()
_CLI_ROOT = Path(__file__).resolve().parents[2]
_MONITOR_STATE_FILE = Path("/tmp/fast-market-monitor.state.json")


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
        models_module = importlib.import_module("core.models")
        executor_module = importlib.import_module("core.executor")
        return storage_module.MonitorStorage, models_module, executor_module
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


def _parse_date(date_str: str | None) -> tuple[datetime, datetime] | None:
    if not date_str:
        return None
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return (start, end)


@router.get("/logs")
def logs(
    since: str | None = Query(None),
    date: str | None = Query(None),
    rule_id: str | None = Query(None),
    source_id: str | None = Query(None),
    action_id: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    mismatch: bool = Query(False),
) -> list[dict]:
    MonitorStorage, _, _ = _get_monitor_storage_class()

    storage = MonitorStorage(get_tool_data_dir("monitor") / "monitor.db")
    since_dt = _parse_since(since)
    date_range = _parse_date(date)
    if date_range:
        since_dt, until_dt = date_range

    if mismatch:
        rows = storage.get_rule_mismatch_logs(
            since=since_dt,
            until=date_range[1] if date_range else None,
            rule_id=rule_id,
            source_id=source_id,
            limit=limit,
            offset=offset,
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

    fetch_limit = limit + offset
    trigger_rows = storage.get_trigger_logs_with_metadata(
        since=since_dt,
        until=date_range[1] if date_range else None,
        rule_id=rule_id,
        source_id=source_id,
        action_id=action_id,
        limit=fetch_limit,
        offset=0,
    )

    error_rows = storage.get_run_error_logs(
        since=since_dt,
        until=date_range[1] if date_range else None,
        source_id=source_id,
        action_id=action_id,
        rule_id=rule_id,
        limit=fetch_limit,
        offset=0,
    )

    # run_error entries with a trigger_log_id are secondary records for an execution
    # already represented by the trigger_log — skip them to avoid duplicates.
    # output_contains_error specifically means the action "succeeded" (exit=0) but the
    # LLM output contains the word "error": flag those trigger_logs as warnings.
    output_error_trigger_ids = {
        r.trigger_log_id
        for r in error_rows
        if r.error_type == "output_contains_error" and r.trigger_log_id
    }

    trigger_data = [
        {
            "id": r.id,
            "log_type": "trigger",
            "rule_id": r.rule_id,
            "source_id": r.source_id,
            "action_id": r.action_id,
            "item_title": r.item_title,
            "triggered_at": r.triggered_at.isoformat(),
            "exit_code": r.exit_code,
            "output": r.output,
            "duration_sec": r.duration_sec,
            "has_output_error": r.id in output_error_trigger_ids,
        }
        for r in trigger_rows
    ]

    # Only keep standalone run_errors (no trigger_log_id) — fetch/plugin/action-not-found errors
    error_data = [
        {
            "id": r.id,
            "log_type": "run_error",
            "error_type": r.error_type,
            "message": r.message,
            "triggered_at": r.logged_at.isoformat(),
            "source_id": r.source_id,
            "action_id": r.action_id,
            "rule_id": r.rule_id,
            "item_title": r.item_title,
            "output": r.output,
            "trigger_log_id": r.trigger_log_id,
        }
        for r in error_rows
        if not r.trigger_log_id
    ]

    combined = trigger_data + error_data
    combined.sort(key=lambda x: x["triggered_at"], reverse=True)
    return combined[offset : offset + limit]


@router.get("/status")
def status() -> dict:
    MonitorStorage, _, _ = _get_monitor_storage_class()

    storage = MonitorStorage(get_tool_data_dir("monitor") / "monitor.db")
    return {
        "statistics": storage.get_stats(),
        "sources": [s.id for s in storage.get_all_sources()],
        "rules": [r.id for r in storage.get_all_rules()],
        "actions": [a.id for a in storage.get_all_actions()],
    }


@router.get("/filters")
def filters() -> dict[str, list[str]]:
    MonitorStorage, _, _ = _get_monitor_storage_class()

    storage = MonitorStorage(get_tool_data_dir("monitor") / "monitor.db")
    return {
        "rule_ids": [r.id for r in storage.get_all_rules()],
        "source_ids": [s.id for s in storage.get_all_sources()],
        "action_ids": [a.id for a in storage.get_all_actions()],
    }


@router.post("/rerun/{trigger_log_id}")
def rerun_action(trigger_log_id: str) -> dict:
    """Rerun an action based on a previous trigger log."""
    MonitorStorage, models_module, executor_module = _get_monitor_storage_class()

    ItemMetadata = models_module.ItemMetadata
    TriggerLog = models_module.TriggerLog
    execute_action = executor_module.execute_action

    storage = MonitorStorage(get_tool_data_dir("monitor") / "monitor.db")

    # Get the specific trigger log by ID
    trigger_log = storage.get_trigger_log(trigger_log_id)
    if not trigger_log:
        raise HTTPException(status_code=404, detail="Trigger log not found")

    # Get the action
    action = storage.get_action(trigger_log.action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    # Get the source
    source = storage.get_source(trigger_log.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Create ItemMetadata from the trigger log
    item = ItemMetadata(
        id=trigger_log.item_id,
        title=trigger_log.item_title,
        url=trigger_log.item_url,
        published_at=None,  # We don't have this in the log
        content_type="",  # We don't have this in the log
        source_plugin=source.plugin,
        source_id=source.id,
        extra=trigger_log.item_extra or {},
    )

    import time as _time
    import uuid
    _rerun_start = _time.monotonic()
    exit_code, output, script_content = execute_action(
        action=action,
        item=item,
        source=source,
        rule_id=trigger_log.rule_id,
    )
    _rerun_duration = int(_time.monotonic() - _rerun_start)

    # Log the rerun
    rerun_log = TriggerLog(
            id=str(uuid.uuid4()),
            rule_id=trigger_log.rule_id,
            source_id=trigger_log.source_id,
            action_id=trigger_log.action_id,
            item_id=trigger_log.item_id,
            item_title=f"[RERUN] {trigger_log.item_title}",
            item_url=trigger_log.item_url,
            triggered_at=datetime.now(timezone.utc),
            exit_code=exit_code,
            output=output,
            item_extra=trigger_log.item_extra,
            duration_sec=_rerun_duration,
        )
    storage.log_trigger(rerun_log)

    return {
        "success": True,
        "exit_code": exit_code,
        "output": output,
        "message": f"Action rerun completed with exit code {exit_code}"
    }


@router.get("/running")
def running_status() -> dict:
    if not _MONITOR_STATE_FILE.exists():
        return {"status": "idle"}
    try:
        data = json.loads(_MONITOR_STATE_FILE.read_text())
        if data.get("status") == "running" and data.get("started_at"):
            started_at = datetime.fromisoformat(data["started_at"])
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            elapsed_sec = int((datetime.now(timezone.utc) - started_at).total_seconds())
            if elapsed_sec > 7200:
                return {"status": "idle", "stale": True}
            data["elapsed_sec"] = elapsed_sec
        return data
    except Exception:
        return {"status": "idle"}


@router.post("/wait")
def monitor_wait() -> dict:
    Path("/tmp/fast-market-monitor.wait").touch()
    return {"success": True}


@router.post("/stop")
def monitor_stop() -> dict:
    Path("/tmp/fast-market-monitor.stop").touch()
    return {"success": True}


@router.post("/diagnose")
def run_diagnose() -> dict:
    import subprocess
    try:
        result = subprocess.run(
            ["bash", "-l", "-c", "toolsetup diagnose -F json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        try:
            data = json.loads(result.stdout)
            return {"success": True, "results": data, "stderr": result.stderr.strip()}
        except Exception:
            return {"success": False, "error": (result.stderr or result.stdout or "No output").strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Diagnose timed out after 120s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


_HTML = """<!doctype html>
<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Monitor</title>
<style>
:root { --bg:#1a1a2e; --surface:#16213e; --accent:#0f3460; --text:#eee; --text-dim:#9ca3af; --border:#334155; --success:#22c55e; --error:#ef4444; --warning:#f59e0b; }
body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }
input, button, select { padding:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:6px; }
button { cursor:pointer; }
button:hover { background:var(--accent); }
.rerun-btn { background:var(--warning); color:#000; border:1px solid var(--warning); }
.rerun-btn:hover { background:#fbbf24; }
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

/* Pagination */
.pagination { display:flex; gap:8px; align-items:center; margin-bottom:12px; }
.pagination button { padding:6px 12px; }
.pagination .current-date { font-weight:600; min-width:140px; text-align:center; }
.pagination .nav-btn:disabled { opacity:0.5; cursor:not-allowed; }
.pagination-info { color:var(--text-dim); font-size:13px; }
.running-panel { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; margin-bottom:16px; }
.running-panel.live { border-color:var(--warning); }
.running-dot { display:inline-block; width:10px; height:10px; border-radius:50%; background:var(--warning); animation:dot-pulse 1.5s ease-in-out infinite; }
@keyframes dot-pulse { 0%,100% { box-shadow:0 0 4px var(--warning); } 50% { box-shadow:0 0 10px 3px var(--warning); } }
.running-grid { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; font-size:13px; margin:10px 0; }
.running-grid .label { color:var(--text-dim); }
.btn-wait { background:var(--warning); color:#000; }
.btn-wait:hover { background:#fbbf24; }
.btn-stop { background:var(--error); color:#fff; }
.btn-stop:hover { background:#dc2626; }
</style></head>
<body>
  <h2>👁 Monitor</h2>
  <div class="row">
    <input id="since" placeholder="since (e.g. 1d, 2h)" style="width:140px;">
    <select id="ruleFilter" style="width:140px;"><option value="">All Rules</option></select>
    <select id="sourceFilter" style="width:140px;"><option value="">All Sources</option></select>
    <select id="actionFilter" style="width:140px;"><option value="">All Actions</option></select>
     <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:13px;">
      <input type="checkbox" id="mismatchToggle"> Mismatches only
    </label>
     <input type="checkbox" id="hideIgnoredActions" checked style="cursor:pointer;">
     <label for="hideIgnoredActions" style="cursor:pointer;font-size:13px;margin-left:4px;">Hide ignored actions</label>
    <button id="loadLogs">📋 Load Logs</button>
    <button id="loadStatus">📊 Status</button>
    <button id="runDiagnose">🔍 Diagnose</button>
  </div>
  <div class="pagination">
    <button id="prevDay" class="nav-btn">◀ Prev Day</button>
    <input type="date" id="datePicker" class="current-date">
    <button id="nextDay" class="nav-btn">Next Day ▶</button>
    <button id="prevPage" class="nav-btn">◀ Prev</button>
    <span id="paginationInfo" class="pagination-info"></span>
    <button id="nextPage" class="nav-btn">Next ▶</button>
  </div>
  <div id="out"></div>
  <script>
  const out = document.getElementById('out');
  const sinceInput = document.getElementById('since');
  const ruleFilter = document.getElementById('ruleFilter');
  const sourceFilter = document.getElementById('sourceFilter');
  const actionFilter = document.getElementById('actionFilter');
  const mismatchToggle = document.getElementById('mismatchToggle');
  const hideIgnoredActions = document.getElementById('hideIgnoredActions');
  const datePicker = document.getElementById('datePicker');
  const prevDayBtn = document.getElementById('prevDay');
  const nextDayBtn = document.getElementById('nextDay');
  const paginationInfo = document.getElementById('paginationInfo');
  const prevPageBtn = document.getElementById('prevPage');
  const nextPageBtn = document.getElementById('nextPage');

  let currentOffset = 0;
  let totalCount = 0;
  const pageSize = 100;

  const today = new Date().toISOString().split('T')[0];
  datePicker.value = today;
  datePicker.max = today;

  function updateNavButtons() {
    const selectedDate = datePicker.value;
    nextDayBtn.disabled = selectedDate >= today;
  }

  prevDayBtn.onclick = () => {
    const d = new Date(datePicker.value);
    d.setDate(d.getDate() - 1);
    datePicker.value = d.toISOString().split('T')[0];
    currentOffset = 0;
    updateNavButtons();
    document.getElementById('loadLogs').click();
  };

  nextDayBtn.onclick = () => {
    const d = new Date(datePicker.value);
    d.setDate(d.getDate() + 1);
    const newVal = d.toISOString().split('T')[0];
    if (newVal <= today) {
      datePicker.value = newVal;
      currentOffset = 0;
      updateNavButtons();
      document.getElementById('loadLogs').click();
    }
  };

  datePicker.onchange = () => {
    currentOffset = 0;
    updateNavButtons();
    document.getElementById('loadLogs').click();
  };

  document.getElementById('prevPage').onclick = () => {
    if (currentOffset >= pageSize) {
      currentOffset -= pageSize;
      document.getElementById('loadLogs').click();
    }
  };

  document.getElementById('nextPage').onclick = () => {
    if (totalCount === pageSize) {
      currentOffset += pageSize;
      document.getElementById('loadLogs').click();
    }
  };

  function updatePaginationButtons() {
    prevPageBtn.disabled = currentOffset === 0;
    nextPageBtn.disabled = totalCount < pageSize;
  }

  async function rerunAction(triggerLogId) {
    if (!confirm('Are you sure you want to rerun this action?')) return;

    try {
      const response = await fetch(`/api/monitor/rerun/${triggerLogId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Rerun failed');
      }

      const result = await response.json();
      alert(`Action rerun completed!\nExit code: ${result.exit_code}\nOutput: ${result.output.slice(0, 200)}...`);

      // Reload logs to show the new execution
      document.getElementById('loadLogs').click();
    } catch (error) {
      alert(`Rerun failed: ${error.message}`);
    }
  }

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

  let runningRefreshTimer = null;
  let runningCounterTimer = null;

  function startRunningCounter(startedAt) {
    clearInterval(runningCounterTimer);
    const startMs = new Date(startedAt).getTime();
    runningCounterTimer = setInterval(() => {
      const el = document.getElementById('runningElapsed');
      if (!el) { clearInterval(runningCounterTimer); return; }
      el.textContent = formatDuration(Math.floor((Date.now() - startMs) / 1000));
    }, 1000);
  }

  function formatDuration(sec) {
    sec = Math.max(0, parseInt(sec) || 0);
    if (sec < 60) return sec + 's';
    const m = Math.floor(sec / 60), s = sec % 60;
    if (m < 60) return m + 'm ' + s + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
  }

  function renderRunning(data) {
    if (!data || data.status === 'idle' || data.stale) {
      let last = '';
      if (data && data.action_id && (data.status === 'success' || data.status === 'failed')) {
        const icon = data.exit_code === 0 ? '✅' : '❌';
        last = ` <span style='font-size:12px;color:var(--text-dim);'>${icon} Last: <strong>${data.action_id}</strong> — ${formatDuration(data.elapsed_sec)}</span>`;
      }
      return `<div id='runningPanel' class='running-panel'><span style='color:var(--text-dim);'>● Monitor idle</span>${last}</div>`;
    }
    if (data.status === 'running') {
      const itemRow = data.item_title ? `<span class='label'>Item:</span><span>${data.item_title.slice(0,80)}</span>` : '';
      return `<div id='runningPanel' class='running-panel live'>
        <div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>
          <span class='running-dot'></span>
          <strong>Running: ${data.action_id || 'unknown'}</strong>
          <span id='runningElapsed' style='color:var(--text-dim);font-size:13px;'>${formatDuration(data.elapsed_sec)}</span>
        </div>
        <div class='running-grid'>
          <span class='label'>Rule:</span><span>${data.rule_id || 'N/A'}</span>
          <span class='label'>Workdir:</span><span style='font-family:monospace;font-size:11px;word-break:break-all;'>${data.workdir || 'N/A'}</span>
          ${itemRow}
          <span class='label'>Started:</span><span>${data.started_at ? formatRelativeTime(data.started_at) : 'N/A'}</span>
        </div>
        <div style='display:flex;gap:8px;margin-top:10px;'>
          <button class='btn-wait' onclick='monitorWait()'>⏳ Wait more (+5min)</button>
          <button class='btn-stop' onclick='monitorStop()'>⏹ Stop</button>
        </div>
      </div>`;
    }
    const icon = data.exit_code === 0 ? '✅' : '❌';
    return `<div id='runningPanel' class='running-panel'><span>${icon} Last: <strong>${data.action_id || 'unknown'}</strong> — ${data.status} — ${formatDuration(data.elapsed_sec)}</span></div>`;
  }

  async function monitorWait() {
    try {
      await fetch('/api/monitor/wait', {method:'POST'});
      alert('Deadline extended by 5min');
    } catch(e) { alert('Error: ' + e.message); }
  }

  async function monitorStop() {
    if (!confirm('Stop the running action?')) return;
    try {
      await fetch('/api/monitor/stop', {method:'POST'});
      alert('Stop signal sent');
    } catch(e) { alert('Error: ' + e.message); }
  }

  const RUN_ERROR_TYPE_LABELS = {
    fetch_error: { cls: 'error', label: 'Fetch Error' },
    plugin_not_found: { cls: 'error', label: 'Plugin Missing' },
    action_not_found: { cls: 'error', label: 'Action Missing' },
    action_exception: { cls: 'error', label: 'Exception' },
    action_exit_error: { cls: 'error', label: 'Exit Error' },
    output_contains_error: { cls: 'warning', label: 'Output Error' },
  };

  function getStatusInfo(exitCode, hasOutputError) {
    if (exitCode !== 0 && exitCode !== null && exitCode !== undefined) return { cls: 'error', label: 'Failed' };
    if (exitCode === null || exitCode === undefined) return { cls: 'warning', label: 'Pending' };
    if (hasOutputError) return { cls: 'warning', label: 'Output Error' };
    return { cls: 'success', label: 'Success' };
  }

  function renderCards(rows, type) {
    if (!rows || rows.length === 0) return '<div style="text-align:center;padding:40px;color:var(--text-dim);">No entries found.</div>';

    // Filter out ignored actions if checkbox is checked
    if (hideIgnoredActions.checked) {
      rows = rows.filter(r => {
        if (!r.action_id) return true; // Keep non-action logs
        // Hide actions that are considered ignored
        return r.action_id !== 'ignored' && !r.action_id.includes('notify');
      });
    }

    return rows.map(r => {
      const triggeredAt = r.triggered_at || r.evaluated_at;
      const relativeTime = formatRelativeTime(triggeredAt);
      const title = r.item_title || '(no title)';

      let status, bodyHtml;

      if (type === 'mismatch') {
        status = { cls: 'warning', label: 'Mismatch' };
        bodyHtml = `<div class="card-body"><div><span class="label">Failed Conditions:</span><pre>${JSON.stringify(r.failed_conditions, null, 2)}</pre></div></div>`;
      } else if (r.log_type === 'run_error') {
        const info = RUN_ERROR_TYPE_LABELS[r.error_type] || { cls: 'warning', label: r.error_type };
        status = info;
        const msgTitle = r.message ? r.message.slice(0, 100) : title;
        bodyHtml = `<div class="card-body">
          <div style="font-size:13px;margin-bottom:6px;">${r.message || ''}</div>
          ${r.trigger_log_id ? `<div style="font-size:12px;color:var(--text-dim);">Trigger: ${r.trigger_log_id}</div>` : ''}
          ${r.output ? `<pre>${r.output}</pre>` : ''}
        </div>`;
      } else {
        status = getStatusInfo(r.exit_code, r.has_output_error);
        bodyHtml = `<div class="card-body">
          <div style="display:grid;grid-template-columns:auto 1fr;gap:6px;font-size:13px;">
            <span class="label">Exit Code:</span><span>${r.exit_code ?? 'N/A'}</span>
            <span class="label">ID:</span><span>${r.id}</span>
            ${r.has_output_error ? `<span class="label">Note:</span><span style="color:var(--warning);">Output contains 'error' keyword</span>` : ''}
          </div>
          ${r.output ? `<pre>${r.output}</pre>` : ''}
        </div>`;
      }

      const cardTitle = (r.log_type === 'run_error' && !r.item_title) ? (r.message || '').slice(0, 80) : title;
      let headerHtml = `
        <span class="status-dot ${status.cls}" title="${status.label}"></span>
        <span class="card-title" title="${cardTitle}">${cardTitle}</span>`;
      if (r.rule_id) headerHtml += ` <span class="card-field"><span class="label">Rule:</span><span class="value badge info">${r.rule_id}</span></span>`;
      if (r.source_id) headerHtml += ` <span class="card-field"><span class="label">Source:</span><span class="value badge info">${r.source_id}</span></span>`;
      if (r.action_id) headerHtml += ` <span class="card-field"><span class="label">Action:</span><span class="value badge info">${r.action_id}</span></span>`;
      headerHtml += ` <span class="card-field"><span class="label">Time:</span><span class="value">${relativeTime}</span></span>`;
      if (r.duration_sec != null) headerHtml += ` <span class="card-field"><span class="label">Duration:</span><span class="value">${formatDuration(r.duration_sec)}</span></span>`;
      headerHtml += ` <span class="badge ${status.cls}">${status.label}</span>`;
      if (r.action_id && r.log_type !== 'run_error') {
        headerHtml += ` <button class="rerun-btn" onclick="event.stopPropagation(); rerunAction('${r.id}')" style="padding:4px 8px;font-size:11px;margin-left:8px;">🔄 Rerun</button>`;
      }
      headerHtml += ` <span class="card-expand">▼</span>`;

      return `<div class="card" onclick="this.classList.toggle('expanded')"><div class="card-header">${headerHtml}</div><div class="card-content">${bodyHtml}</div></div>`;
    }).join('');
  }

  function renderStats(data) {
    const stats = data.statistics || {};
    const total = stats.triggers_count || 0;
    const failed = stats.failed_triggers_count || 0;
    const success = total - failed;
    const successRate = total > 0 ? ((success / total) * 100).toFixed(1) : '0';
    const todayTotal = stats.triggers_today || 0;
    const todayFailed = stats.failed_today || 0;
    const todaySuccess = todayTotal - todayFailed;
    const todayRate = todayTotal > 0 ? ((todaySuccess / todayTotal) * 100).toFixed(1) : '0';
    const rateColor = (r) => r >= 80 ? 'var(--success)' : r >= 50 ? 'var(--warning)' : 'var(--error)';
    return `
      <div class="stats-grid" style="margin-bottom:4px;">
        <div class="stat-card"><div class="stat-label">All time — Triggers</div><div class="stat-value">${total}</div></div>
        <div class="stat-card"><div class="stat-label">All time — Success</div><div class="stat-value" style="color:var(--success)">${success}</div></div>
        <div class="stat-card"><div class="stat-label">All time — Failed</div><div class="stat-value" style="color:var(--error)">${failed}</div></div>
        <div class="stat-card"><div class="stat-label">All time — Rate</div><div class="stat-value" style="color:${rateColor(successRate)}">${successRate}%</div></div>
      </div>
      <div class="stats-grid" style="margin-bottom:16px;">
        <div class="stat-card"><div class="stat-label">Today — Triggers</div><div class="stat-value">${todayTotal}</div></div>
        <div class="stat-card"><div class="stat-label">Today — Success</div><div class="stat-value" style="color:var(--success)">${todaySuccess}</div></div>
        <div class="stat-card"><div class="stat-label">Today — Failed</div><div class="stat-value" style="color:var(--error)">${todayFailed}</div></div>
        <div class="stat-card"><div class="stat-label">Today — Rate</div><div class="stat-value" style="color:${rateColor(todayRate)}">${todayRate}%</div></div>
      </div>
      <div class="filter-section">
        <div class="card-field"><span class="label">Sources:</span> ${(data.sources || []).map(s => `<span class="badge info">${s}</span>`).join(' ')}</div>
        <div class="card-field" style="margin-top:6px;"><span class="label">Rules:</span> ${(data.rules || []).map(r => `<span class="badge info">${r}</span>`).join(' ')}</div>
        <div class="card-field" style="margin-top:6px;"><span class="label">Actions:</span> ${(data.actions || []).map(a => `<span class="badge info">${a}</span>`).join(' ')}</div>
      </div>`;
  }

  function renderDiagnose(data) {
    if (!data.success) {
      return `<div style='color:var(--error);padding:16px;background:var(--surface);border-radius:8px;border:1px solid var(--border);'><strong>Diagnose failed:</strong><pre style='margin-top:8px;'>${data.error || 'Unknown error'}</pre></div>`;
    }
    const results = data.results || [];
    const statusConfig = {ok:{cls:'success',icon:'✓'}, warning:{cls:'warning',icon:'⚠'}, error:{cls:'error',icon:'✗'}};
    const cards = results.map(r => {
      const sc = statusConfig[r.status] || {cls:'info',icon:'?'};
      const details = r.details && Object.keys(r.details).length
        ? `<div style='font-size:12px;color:var(--text-dim);margin-top:6px;'>${Object.entries(r.details).map(([k,v])=>`<span>${k}: <code style='background:var(--bg);padding:1px 4px;border-radius:3px;'>${v}</code></span>`).join(' · ')}</div>` : '';
      const recs = r.recommendations && r.recommendations.length
        ? `<div style='margin-top:8px;font-size:12px;'><span style='color:var(--text-dim);'>Recommendations:</span><ul style='margin:4px 0 0 16px;padding:0;'>${r.recommendations.map(rec=>`<li>${rec}</li>`).join('')}</ul></div>` : '';
      return `<div class='card' style='cursor:default;'><div class='card-header' style='cursor:default;'><span class='status-dot ${sc.cls}'></span><span class='card-title'>${r.test}</span><span class='badge ${sc.cls}'>${sc.icon} ${r.status}</span></div><div style='padding:0 16px 12px;font-size:13px;'><div>${r.message}</div>${details}${recs}</div></div>`;
    }).join('');
    const ok = results.filter(r=>r.status==='ok').length;
    const warn = results.filter(r=>r.status==='warning').length;
    const err = results.filter(r=>r.status==='error').length;
    const col = err > 0 ? 'var(--error)' : warn > 0 ? 'var(--warning)' : 'var(--success)';
    const summary = `<div style='margin-bottom:12px;padding:10px 14px;background:var(--surface);border-radius:8px;border-left:3px solid ${col};font-size:14px;'><strong>Diagnostics</strong> — <span style='color:var(--success);'>${ok} ok</span>, <span style='color:var(--warning);'>${warn} warning</span>, <span style='color:var(--error);'>${err} error</span></div>`;
    const stderr = data.stderr ? `<div style='font-size:11px;color:var(--text-dim);margin-top:8px;'><pre style='background:var(--bg);'>${data.stderr}</pre></div>` : '';
    return summary + cards + stderr;
  }

  document.getElementById('runDiagnose').onclick = async () => {
    clearInterval(runningRefreshTimer);
    clearInterval(runningCounterTimer);
    out.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-dim);">🔍 Running diagnostics…</div>';
    try {
      const r = await fetch('/api/monitor/diagnose', {method:'POST'});
      const data = await r.json();
      out.innerHTML = renderDiagnose(data);
    } catch(e) {
      out.innerHTML = `<div style='color:var(--error);padding:16px;'>Failed: ${e.message}</div>`;
    }
  };

  async function loadFilters() {
    try {
      const r = await fetch('/api/monitor/filters');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      (data.rule_ids || []).forEach(id => { if (![...ruleFilter.options].some(o => o.value === id)) { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; ruleFilter.appendChild(opt); } });
      (data.source_ids || []).forEach(id => { if (![...sourceFilter.options].some(o => o.value === id)) { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; sourceFilter.appendChild(opt); } });
      (data.action_ids || []).forEach(id => { if (![...actionFilter.options].some(o => o.value === id)) { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; actionFilter.appendChild(opt); } });
    } catch(e) { console.error('Failed to load filters:', e); }
  }

  function populateFiltersFromLogs(data) {
    const ruleIds = new Set(), sourceIds = new Set(), actionIds = new Set();
    data.forEach(r => {
      if (r.rule_id) ruleIds.add(r.rule_id);
      if (r.source_id) sourceIds.add(r.source_id);
      if (r.action_id) actionIds.add(r.action_id);
    });
    ruleIds.forEach(id => { if (![...ruleFilter.options].some(o => o.value === id)) { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; ruleFilter.appendChild(opt); } });
    sourceIds.forEach(id => { if (![...sourceFilter.options].some(o => o.value === id)) { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; sourceFilter.appendChild(opt); } });
    actionIds.forEach(id => { if (![...actionFilter.options].some(o => o.value === id)) { const opt = document.createElement('option'); opt.value = id; opt.textContent = id; actionFilter.appendChild(opt); } });
  }

  hideIgnoredActions.addEventListener('change', () => {
    document.getElementById('loadLogs').click();
  });

  document.getElementById('loadLogs').onclick = async () => {
    clearInterval(runningRefreshTimer);
    clearInterval(runningCounterTimer);
    const since = sinceInput.value.trim();
    const rule = ruleFilter.value;
    const source = sourceFilter.value;
    const action = actionFilter.value;
    const mismatch = mismatchToggle.checked;
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    if (datePicker.value) params.set('date', datePicker.value);
    if (rule) params.set('rule_id', rule);
    if (source) params.set('source_id', source);
    if (action) params.set('action_id', action);
    if (mismatch) params.set('mismatch', 'true');
    params.set('limit', String(pageSize));
    params.set('offset', String(currentOffset));
    const q = params.toString() ? '?' + params.toString() : '';
    const r = await fetch('/api/monitor/logs' + q);
    const data = await r.json();
    const type = mismatch ? 'mismatch' : 'trigger';
    populateFiltersFromLogs(data);
    out.innerHTML = renderCards(data, type);
    totalCount = data.length;
    const pageStart = currentOffset + 1;
    const pageEnd = currentOffset + data.length;
    paginationInfo.textContent = data.length > 0 ? `Showing ${pageStart}-${pageEnd}` : 'No results';
    updatePaginationButtons();
  };

  document.getElementById('loadStatus').onclick = async () => {
    clearInterval(runningRefreshTimer);
    clearInterval(runningCounterTimer);
    const [statusR, runningR] = await Promise.all([fetch('/api/monitor/status'), fetch('/api/monitor/running')]);
    const statsData = await statusR.json();
    const runningData = await runningR.json();
    out.innerHTML = renderRunning(runningData) + renderStats(statsData);
    if (runningData.status === 'running') {
      if (runningData.started_at) startRunningCounter(runningData.started_at);
      runningRefreshTimer = setInterval(async () => {
        const r = await fetch('/api/monitor/running');
        const d = await r.json();
        const panel = document.getElementById('runningPanel');
        if (panel) panel.outerHTML = renderRunning(d);
        if (d.status === 'running') {
          if (d.started_at) startRunningCounter(d.started_at);
        } else {
          clearInterval(runningRefreshTimer);
          clearInterval(runningCounterTimer);
        }
      }, 5000);
    }
  };

  // Load filters then auto-load logs on startup
  loadFilters().then(() => {
    document.getElementById('loadLogs').click();
  });
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
