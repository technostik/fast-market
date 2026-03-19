from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
from core.rule_engine import evaluate_rule
from core.executor import execute_action
from core.models import TriggerLog

_TOOL_ROOT = Path(__file__).resolve().parents[2]


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("run")
    @click.option("--cron", is_flag=True, help="Run in cron mode (no output unless errors)")
    @click.option("--source-id", help="Run only for specific source")
    @click.option("--dry-run", is_flag=True, help="Evaluate rules without executing actions")
    @click.option(
        "--force",
        is_flag=True,
        help="Ignore last_fetched_at, process all available items (for testing)",
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
        """Check sources and execute matching rules.

        Use --force to re-process already seen items for testing.
        """
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

        for source in sources:
            if source.plugin not in plugin_manifests:
                errors.append(f"Plugin {source.plugin} not found for source {source.id}")
                continue

            plugin_cls = plugin_manifests[source.plugin].source_plugin_class
            plugin_instance = plugin_cls(config, {"identifier": source.identifier})

            try:
                if force:
                    if not cron:
                        click.echo(
                            f"⚠️  FORCE MODE: Processing up to {limit} items from {source.identifier}",
                            err=True,
                        )
                    items = asyncio.run(
                        plugin_instance.fetch_new_items(
                            last_item_id=None, limit=limit, last_fetched_at=None
                        )
                    )
                else:
                    items = asyncio.run(
                        plugin_instance.fetch_new_items(
                            last_item_id=None, limit=limit, last_fetched_at=source.last_fetched_at
                        )
                    )
            except Exception as e:
                errors.append(f"Failed to fetch from {source.identifier}: {str(e)}")
                continue

            for item in items:
                for rule in rules:
                    try:
                        if evaluate_rule(rule, item, source):
                            triggered.append({"rule": rule, "item": item, "source": source})
                    except Exception as e:
                        errors.append(f"Rule evaluation error for {rule.name}: {str(e)}")

            if items and not force:
                newest_item = max(items, key=lambda x: x.published_at)
                source.last_fetched_at = newest_item.published_at
                storage.update_source_last_fetched_at(source.id, source.last_fetched_at)
            elif force and items:
                if not cron:
                    click.echo(
                        f"  → Force mode: NOT updating last_fetched_at",
                        err=True,
                    )

        for entry in triggered:
            rule = entry["rule"]
            item = entry["item"]
            source = entry["source"]

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
                                    triggered_at=datetime.now(timezone.utc),
                                    exit_code=code,
                                    output=output,
                                )
                            )

                            action.last_run = datetime.now(timezone.utc)
                            action.last_output = output
                            action.last_exit_code = code
                            storage.update_action(action)

                            if code != 0:
                                errors.append(f"Action {action.name} failed with exit code {code}")
                        except Exception as e:
                            errors.append(f"Action execution error for {action.name}: {str(e)}")

        if not cron:
            result = {
                "mode": "force" if force else "normal",
                "checked_sources": len(sources),
                "triggered_rules": len(triggered),
                "limit_per_source": limit if force else "unlimited",
                "errors": errors,
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
        elif errors:
            for error in errors:
                click.echo(f"[ERROR] {error}", err=True)

    return CommandManifest(
        name="run",
        click_command=run_cmd,
    )
