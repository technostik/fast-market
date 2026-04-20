from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
from core.models import RunErrorLog

_TOOL_ROOT = Path(__file__).resolve().parents[2]


def _detect_format_from_filename(filename: str) -> str:
    if filename.endswith(".yaml") or filename.endswith(".yml"):
        return "yaml"
    elif filename.endswith(".json"):
        return "json"
    return "json"


def _fetch_items_for_diagnose(source, plugin_cls, config, limit, cron, storage):
    import time

    plugin_metadata = {**source.metadata}
    if source.slowdown:
        plugin_metadata["slowdown"] = source.slowdown

    plugin_instance = plugin_cls(
        config,
        {
            "id": source.id,
            "origin": source.origin,
            "metadata": plugin_metadata,
            "last_check": source.last_check,
            "slowdown": source.slowdown,
        },
    )

    if not cron:
        click.echo(
            f"📥 Fetching source='{source.id}' plugin={source.plugin} limit={limit}", err=True
        )

    fetch_start = time.time()
    import asyncio

    try:
        items = asyncio.run(
            plugin_instance.fetch_new_items(
                last_item_id=None,
                limit=limit,
                force=True,
                date_filter="today",
            )
        )
    except Exception as e:
        if not cron:
            click.echo(f"[ERROR] Fetch failed for source='{source.id}': {e}", err=True)
        storage.log_run_error(
            RunErrorLog(
                id=str(uuid.uuid4()),
                error_type="fetch_error",
                message=f"Fetch failed for source='{source.id}': {e}",
                logged_at=datetime.now(timezone.utc),
                source_id=source.id,
                output=str(e),
            )
        )
        return []

    fetch_time = time.time() - fetch_start
    raw_count = getattr(plugin_instance, "_rss_raw_count", len(items))
    if not cron and raw_count > 0:
        click.echo(f"  → fetched {raw_count} items in {fetch_time:.1f}s", err=True)

    return items


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("diagnose")
    @click.option("--cron", is_flag=True, help="Run in cron mode (no output unless errors)")
    @click.option(
        "--limit", type=int, default=100, help="Max items to fetch per source (default: 100)"
    )
    @click.option("--format", "fmt", type=click.Choice(["json", "text", "yaml"]), default="yaml")
    @click.option(
        "-f",
        "--output-file",
        "output_file",
        help="Output file path (format autodetected from extension)",
    )
    @click.pass_context
    def diagnose_cmd(ctx, cron, limit, fmt, output_file):
        storage = get_storage()
        now = datetime.now(timezone.utc)
        today = now.date()

        sources = storage.get_all_sources(include_disabled=False)
        if not sources:
            if not cron:
                out_formatted(
                    {"error": "No sources found. Run 'monitor setup source-add' first."},
                    fmt,
                )
            return

        config = {}
        all_items = []
        errors = []

        for source in sources:
            if source.plugin not in plugin_manifests:
                error_msg = f"Plugin '{source.plugin}' not found for source '{source.id}'"
                errors.append(error_msg)
                click.echo(f"[ERROR] {error_msg}", err=True)
                storage.log_run_error(
                    RunErrorLog(
                        id=str(uuid.uuid4()),
                        error_type="plugin_not_found",
                        message=error_msg,
                        logged_at=now,
                        source_id=source.id,
                    )
                )
                continue

            plugin_cls = plugin_manifests[source.plugin].source_plugin_class
            items = _fetch_items_for_diagnose(source, plugin_cls, config, limit, cron, storage)
            all_items.extend([{"item": item, "source": source} for item in items])

        # Filter to today's videos
        today_items = [entry for entry in all_items if entry["item"].published_at.date() == today]

        total_fetched = len(all_items)
        total_today = len(today_items)

        if total_fetched < 10:
            click.echo(
                f"[WARNING] Only {total_fetched} items fetched total, less than 10", err=True
            )

        # Get all logged item_ids and their logs
        logged_item_ids = storage.get_all_logged_item_ids()

        # For each today item, determine status
        today_videos = []
        for entry in today_items:
            item = entry["item"]
            source = entry["source"]
            item_id = item.id

            if item_id in logged_item_ids:
                # Get the log entry - assume the latest one
                log = storage.get_trigger_log_for_item(item_id)
                if log:
                    if log.rule_id == "ignored":
                        status = "ignored"
                    elif log.exit_code != 0:
                        status = "error"
                    else:
                        status = "triggered"
                else:
                    status = "logged_but_no_details"  # shouldn't happen
            else:
                status = "unfound"
                log = None

            today_videos.append(
                {
                    "item_id": item_id,
                    "title": item.title,
                    "url": item.url,
                    "published": item.published_at.isoformat(),
                    "source_id": source.id,
                    "source_plugin": source.plugin,
                    "status": status,
                    "log": {
                        "rule_id": log.rule_id if log else None,
                        "action_id": log.action_id if log else None,
                        "exit_code": log.exit_code if log else None,
                        "output": log.output if log else None,
                        "triggered_at": log.triggered_at if log else None,
                    }
                    if log
                    else None,
                }
            )

        # Find missing (unfound)
        missing = [v for v in today_videos if v["status"] == "unfound"]

        result = {
            "total_fetched": total_fetched,
            "total_today": total_today,
            "total_logged": len(logged_item_ids),
            "total_missing": len(missing),
            "today_videos": today_videos,
            "missing_videos": missing,
            "errors": errors,
        }

        if not cron:
            if output_file:
                output_fmt = _detect_format_from_filename(output_file)
                with open(output_file, "w") as f:
                    if output_fmt == "yaml":
                        yaml.dump(result, f, default_flow_style=False)
                    else:
                        json.dump(result, f, indent=2)
            else:
                out_formatted(result, fmt)

    return CommandManifest(
        name="diagnose",
        click_command=diagnose_cmd,
    )
