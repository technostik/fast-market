from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
from core.executor import execute_action
from core.models import TriggerLog
from core.rule_engine import evaluate_rule
from core.time_scheduler import should_run_rule

_TOOL_ROOT = Path(__file__).resolve().parents[2]


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("run")
    @click.option("--cron", is_flag=True, help="Run in cron mode (no output unless errors)")
    @click.option("--source-id", help="Run only for specific source")
    @click.option("--dry-run", is_flag=True, help="Evaluate rules without executing actions")
    @click.option(
        "--force",
        is_flag=True,
        help="Ignore cooldown, process all available items (for testing)",
    )
    @click.option(
        "--limit", type=int, default=50, help="Max items to process per source (default: 50)"
    )
    @click.option(
        "--silent",
        is_flag=True,
        help="Suppress replay of command output (action results will still be logged)",
    )
    @click.option("--format", "fmt", type=click.Choice(["json", "text", "yaml"]), default="text")
    @click.pass_context
    def run_cmd(ctx, cron, source_id, dry_run, force, limit, silent, fmt):
        storage = get_storage()

        sources = storage.get_all_sources()
        if source_id:
            sources = [s for s in sources if s.id == source_id]

        if not sources:
            if not cron:
                out_formatted(
                    {"error": "No enabled sources found. Run 'monitor setup source-add' first."},
                    fmt,
                )
            return

        config = {}

        rules = storage.get_all_rules()
        if not rules:
            if not cron:
                out_formatted(
                    {"error": "No enabled rules found. Run 'monitor setup rule-add' first."},
                    fmt,
                )
            return

        triggered = []
        errors = []
        source_stats = {}

        for source in sources:
            source_id_str = source.identifier
            if len(source_id_str) > 40:
                source_id_str = source_id_str[:37] + "..."

            if source.plugin not in plugin_manifests:
                error_msg = f"Plugin '{source.plugin}' not found for source '{source.id}'"
                errors.append(error_msg)
                click.echo(f"[ERROR] {error_msg}", err=True)
                continue

            plugin_cls = plugin_manifests[source.plugin].source_plugin_class
            plugin_instance = plugin_cls(
                config,
                {
                    "identifier": source.identifier,
                    "metadata": source.metadata,
                    "last_check": source.last_check,
                },
            )

            cooldown_active = not plugin_instance._should_fetch()
            items = []
            fetch_error = None

            try:
                if cooldown_active:
                    if force:
                        if not cron:
                            remaining = _get_cooldown_remaining(plugin_instance)
                            click.echo(
                                f"⚠️  FORCE: Bypassing cooldown for '{source_id_str}' "
                                f"(cooldown: {remaining} remaining)",
                                err=True,
                            )
                    else:
                        if not cron:
                            remaining = _get_cooldown_remaining(plugin_instance)
                            click.echo(
                                f"[COOLDOWN] '{source_id_str}' - "
                                f"skipped (cooldown: {remaining} remaining)",
                                err=True,
                            )
                        source_stats[source.id] = {
                            "fetched": 0,
                            "filtered": 0,
                            "skipped": "cooldown",
                        }
                        continue

                if force:
                    if not cron:
                        click.echo(
                            f"⚡  FORCE: Processing up to {limit} items from '{source_id_str}'",
                            err=True,
                        )
                    items = asyncio.run(
                        plugin_instance.fetch_new_items(
                            last_item_id=None, limit=limit, last_fetched_at=None, force=True
                        )
                    )
                else:
                    items = asyncio.run(
                        plugin_instance.fetch_new_items(
                            last_item_id=None, limit=limit, last_fetched_at=source.last_fetched_at
                        )
                    )
            except Exception as e:
                fetch_error = str(e)
                error_msg = f"Fetch failed for '{source_id_str}': {fetch_error}"
                errors.append(error_msg)
                click.echo(f"[ERROR] {error_msg}", err=True)

            if fetch_error:
                source_stats[source.id] = {"fetched": 0, "filtered": 0, "error": fetch_error}
                continue

            fetched_count = len(items)

            if items and not force:
                newest_item = max(items, key=lambda x: x.published_at)
                source.last_fetched_at = newest_item.published_at
                storage.update_source_last_fetched_at(source.id, source.last_fetched_at)

            if not force:
                now = datetime.now(timezone.utc)
                source.last_check = now
                storage.update_source_last_check_time(source.id, now)

            matched_items = []
            for item in items:
                for rule in rules:
                    try:
                        if not should_run_rule(rule):
                            continue
                        if evaluate_rule(rule, item, source):
                            triggered.append({"rule": rule, "item": item, "source": source})
                            matched_items.append(item.id)
                    except Exception as e:
                        error_msg = f"Rule evaluation error for '{rule.name}': {str(e)}"
                        errors.append(error_msg)
                        click.echo(f"[ERROR] {error_msg}", err=True)

            filtered_count = fetched_count - len(set(matched_items))

            source_stats[source.id] = {
                "fetched": fetched_count,
                "matched": len(matched_items),
                "filtered": filtered_count,
            }

            if not cron and not silent:
                if fetched_count == 0:
                    click.echo(f"  → '{source_id_str}': no items", err=True)
                else:
                    click.echo(
                        f"  → '{source_id_str}': fetched={fetched_count}, "
                        f"matched={len(matched_items)}, filtered={filtered_count}",
                        err=True,
                    )

            if force and items:
                if not cron:
                    click.echo(
                        "  → Force mode: NOT updating last_fetched_at or last_check",
                        err=True,
                    )

        for entry in triggered:
            rule = entry["rule"]
            item = entry["item"]
            source = entry["source"]

            triggered_at = datetime.now(timezone.utc)
            if not dry_run:
                for action_id in rule.action_ids:
                    action = storage.get_action(action_id)
                    if action and action.enabled:
                        try:
                            code, output = execute_action(action, item, source, rule.name)

                            if not silent and not cron:
                                click.echo(f"[{action.name}] exit={code}")
                                if output:
                                    click.echo(output)

                            storage.log_trigger(
                                TriggerLog(
                                    id=str(uuid.uuid4()),
                                    rule_id=rule.id,
                                    source_id=source.id,
                                    action_id=action.id,
                                    item_id=item.id,
                                    item_title=item.title,
                                    item_url=item.url,
                                    item_extra=item.extra,
                                    triggered_at=triggered_at,
                                    exit_code=code,
                                    output=output,
                                )
                            )

                            storage.update_rule_last_triggered_at(rule.id, triggered_at)

                            action.last_run = triggered_at
                            action.last_output = output
                            action.last_exit_code = code
                            storage.update_action(action)

                            if code != 0:
                                error_msg = f"Action '{action.name}' failed with exit code {code}"
                                errors.append(error_msg)
                                click.echo(f"[ERROR] {error_msg}", err=True)
                        except Exception as e:
                            error_msg = f"Action execution error for '{action.name}': {str(e)}"
                            errors.append(error_msg)
                            click.echo(f"[ERROR] {error_msg}", err=True)

        if not cron:
            result = {
                "mode": "force" if force else "normal",
                "checked_sources": len(sources),
                "triggered_rules": len(triggered),
                "limit_per_source": limit,
                "errors": errors,
                "source_stats": source_stats,
                "triggers": [
                    {
                        "rule": r["rule"].name,
                        "rule_id": r["rule"].id,
                        "source": r["source"].identifier,
                        "source_id": r["source"].id,
                        "source_metadata": r["source"].metadata,
                        "item": {
                            "id": r["item"].id,
                            "title": r["item"].title,
                            "url": r["item"].url,
                            "content_type": r["item"].content_type,
                            "published": r["item"].published_at.isoformat(),
                            "extra": r["item"].extra,
                        },
                    }
                    for r in triggered
                ],
            }
            out_formatted(result, fmt)

        if errors and cron:
            for error in errors:
                click.echo(f"[ERROR] {error}", err=True)

    return CommandManifest(
        name="run",
        click_command=run_cmd,
    )


def _get_cooldown_remaining(plugin_instance) -> str:
    if plugin_instance.last_check is None:
        return "none"

    try:
        interval_seconds = plugin_instance._parse_interval()
        now = datetime.now(timezone.utc)

        if isinstance(plugin_instance.last_check, str):
            last_check_dt = datetime.fromisoformat(plugin_instance.last_check)
            if last_check_dt.tzinfo is None:
                last_check_dt = last_check_dt.replace(tzinfo=timezone.utc)
        else:
            last_check_dt = plugin_instance.last_check

        elapsed = (now - last_check_dt).total_seconds()
        remaining = interval_seconds - elapsed

        if remaining <= 0:
            return "0s"
        if remaining < 60:
            return f"{int(remaining)}s"
        elif remaining < 3600:
            return f"{int(remaining / 60)}m"
        else:
            return f"{int(remaining / 3600)}h"
    except Exception:
        return "unknown"
