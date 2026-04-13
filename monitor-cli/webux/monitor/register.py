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
:root { --bg:#1a1a2e; --surface:#16213e; --accent:#0f3460; --text:#eee; --text-dim:#9ca3af; --border:#334155; }
body { margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }
input, button { padding:8px; border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:6px; }
.row { display:flex; gap:8px; margin-bottom:10px; }
pre { white-space:pre-wrap; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:10px; }
</style></head>
<body>
  <h2>Monitor</h2>
  <div class="row"><input id="since" placeholder="since e.g. 1d"><button id="loadLogs">Load Logs</button><button id="loadStatus">Status</button></div>
  <pre id="out">Ready.</pre>
  <script>
  const out = document.getElementById('out');
  const show = (v) => out.textContent = JSON.stringify(v, null, 2);
  document.getElementById('loadLogs').onclick = async () => {
    const since = document.getElementById('since').value.trim();
    const q = since ? `?since=${encodeURIComponent(since)}` : '';
    const r = await fetch('/api/monitor/logs'+q); show(await r.json());
  };
  document.getElementById('loadStatus').onclick = async () => {
    const r = await fetch('/api/monitor/status'); show(await r.json());
  };
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
