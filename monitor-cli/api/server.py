from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from ruamel.yaml import YAML

from common.core.config import load_tool_config
from common.core.paths import get_tool_config_path

app = FastAPI(title="monitor-agent")
_TOOL_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND = _TOOL_ROOT / "ui"


def _get_storage():
    from core.storage import MonitorStorage
    from common.core.paths import get_tool_data_dir

    data_dir = get_tool_data_dir("monitor")
    db_path = data_dir / "monitor.db"
    return MonitorStorage(db_path)


def _html(name: str) -> HTMLResponse:
    path = _FRONTEND / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file missing: {path}")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/logs")


for route, page in [
    ("/ui/logs", "logs.html"),
    ("/ui/status", "status.html"),
    ("/ui/debug", "debug.html"),
]:
    app.add_api_route(
        route, (lambda p=page: _html(p)), methods=["GET"], response_class=HTMLResponse
    )


@app.get("/api/logs")
def get_logs(
    since: str | None = Query(None),
    rule_id: str | None = Query(None),
    source_id: str | None = Query(None),
    action_id: str | None = Query(None),
    limit: int = Query(100, le=500),
    mismatch: bool = Query(False),
) -> list[dict]:
    storage = _get_storage()

    since_dt = _parse_since(since) if since else None

    if mismatch:
        logs = storage.get_rule_mismatch_logs(
            since=since_dt, rule_id=rule_id, source_id=source_id, limit=limit
        )
        return [
            {
                "id": log.id,
                "rule_id": log.rule_id,
                "source_id": log.source_id,
                "item_id": log.item_id,
                "item_title": log.item_title,
                "failed_conditions": log.failed_conditions,
                "evaluated_at": log.evaluated_at.isoformat(),
            }
            for log in logs
        ]

    logs = storage.get_trigger_logs_with_metadata(
        since=since_dt, rule_id=rule_id, source_id=source_id, action_id=action_id, limit=limit
    )
    return [
        {
            "id": log.id,
            "rule_id": log.rule_id,
            "source_id": log.source_id,
            "action_id": log.action_id,
            "item_id": log.item_id,
            "item_title": log.item_title,
            "item_url": log.item_url,
            "item_extra": log.item_extra,
            "triggered_at": log.triggered_at.isoformat(),
            "exit_code": log.exit_code,
            "output": log.output[:500] if log.output and len(log.output) > 500 else log.output,
        }
        for log in logs
    ]


@app.get("/api/status")
def get_status() -> dict:
    storage = _get_storage()
    stats = storage.get_stats()

    sources = storage.get_all_sources()
    rules = storage.get_all_rules()
    actions = storage.get_all_actions()

    return {
        "statistics": stats,
        "sources": [
            {
                "id": s.id,
                "plugin": s.plugin,
                "origin": s.origin,
                "last_check": s.last_check.isoformat() if s.last_check else None,
                "last_item_id": s.last_item_id,
            }
            for s in sources
        ],
        "rules": [
            {
                "id": r.id,
                "action_ids": r.action_ids,
                "last_triggered_at": r.last_triggered_at.isoformat()
                if r.last_triggered_at
                else None,
            }
            for r in rules
        ],
        "actions": [
            {
                "id": a.id,
                "last_run": a.last_run.isoformat() if a.last_run else None,
                "last_exit_code": a.last_exit_code,
            }
            for a in actions
        ],
    }


@app.get("/api/filters")
def get_filters() -> dict:
    storage = _get_storage()

    sources = storage.get_all_sources()
    rules = storage.get_all_rules()
    actions = storage.get_all_actions()

    return {
        "rule_ids": [r.id for r in rules],
        "source_ids": [s.id for s in sources],
        "action_ids": [a.id for a in actions],
    }


@app.get("/api/debug/seen-items")
def get_seen_items_debug(source_id: str | None = Query(None)) -> dict:
    storage = _get_storage()

    if source_id:
        items = storage.get_seen_items_for_source(source_id)
        count = storage.get_seen_items_count(source_id)
        return {
            "source_id": source_id,
            "count": count,
            "items": items,
        }
    else:
        all_items = storage.get_all_seen_items_grouped()
        return {
            "sources": [
                {
                    "source_id": sid,
                    "count": len(items),
                    "items": items[:50],  # First 50 for preview
                }
                for sid, items in all_items.items()
            ],
            "total_sources": len(all_items),
        }


@app.get("/api/debug/source/{source_id}")
def get_source_debug(source_id: str) -> dict:
    storage = _get_storage()
    source = storage.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    seen_items = storage.get_seen_items_for_source(source_id)
    seen_ids = storage.get_seen_item_ids(source_id)

    return {
        "source": {
            "id": source.id,
            "plugin": source.plugin,
            "origin": source.origin,
            "is_new": source.is_new,
            "last_item_id": source.last_item_id,
            "last_fetched_at": source.last_fetched_at.isoformat()
            if source.last_fetched_at
            else None,
            "last_check": source.last_check.isoformat() if source.last_check else None,
        },
        "seen_items_count": len(seen_items),
        "seen_ids_sample": list(seen_ids)[:20],
        "seen_items": [
            {
                "item_id": item.item_id,
                "published_at": item.published_at.isoformat(),
                "seen_at": item.seen_at.isoformat(),
            }
            for item in seen_items
        ],
    }


@app.get("/api/config")
def get_config() -> dict:
    cfg_path = get_tool_config_path("monitor").parent / "monitor.yaml"
    if not cfg_path.exists():
        return {"error": "Config file not found"}

    yaml = YAML()
    yaml.preserve_quotes = True
    with open(cfg_path) as f:
        config = yaml.load(f)

    return {"config": config, "path": str(cfg_path)}


@app.post("/api/config/sync")
def sync_config() -> dict:
    cfg_path = get_tool_config_path("monitor").parent / "monitor.yaml"
    if not cfg_path.exists():
        return {"error": "Config file not found. Run 'monitor config export' first."}

    storage = _get_storage()

    from commands.config.register import _sync_config_logic
    from common.core.config import load_tool_config

    config = load_tool_config("monitor")
    from common.core.registry import discover_plugins

    plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)

    result = _sync_config_logic(storage, cfg_path, plugin_manifests, dry_run=False)
    return result


def _parse_since(since: str) -> datetime:
    now = datetime.now()
    if since.endswith("d"):
        return now - timedelta(days=int(since[:-1]))
    elif since.endswith("h"):
        return now - timedelta(hours=int(since[:-1]))
    elif since.endswith("m"):
        return now - timedelta(minutes=int(since[:-1]))
    else:
        try:
            return datetime.fromisoformat(since)
        except ValueError:
            return now - timedelta(days=1)


_load_plugins_called = False


def _load() -> None:
    global _load_plugins_called
    if _load_plugins_called:
        return
    _load_plugins_called = True

    from common.core.registry import discover_commands, discover_plugins
    from common.core.config import load_tool_config

    config = load_tool_config("monitor")
    plugins = discover_plugins(config, tool_root=_TOOL_ROOT)
    commands = discover_commands(plugins, tool_root=_TOOL_ROOT)

    for manifest in list(plugins.values()) + list(commands.values()):
        if hasattr(manifest, "api_router") and manifest.api_router:
            app.include_router(manifest.api_router)


_load()
