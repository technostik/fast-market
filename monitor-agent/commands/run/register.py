from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
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
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def run_cmd(ctx, cron, source_id, dry_run, fmt):
        """Check sources and execute matching rules."""
        storage = get_storage()

        sources = storage.get_all_sources()
        if source_id:
            sources = [s for s in sources if s.id == source_id]

        if not sources:
            if not cron:
                out_formatted(
                    {
                        "error": "No enabled sources found. Run 'monitor-agent setup source-add' first."
                    },
                    fmt,
                )
            return

        config = {}

        rules = storage.get_all_rules()
        if not rules:
            if not cron:
                out_formatted(
                    {"error": "No enabled rules found. Run 'monitor-agent setup rule-add' first."},
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
                items = asyncio.run(
                    plugin_instance.fetch_new_items(last_item_id=source.last_item_id)
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

                if items:
                    source.last_item_id = item.id

            if items:
                storage.update_source_last_check(
                    source.id, items[-1].id if items else source.last_item_id
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

                            storage.log_trigger(
                                TriggerLog(
                                    id=str(uuid.uuid4()),
                                    rule_id=rule.id,
                                    source_id=source.id,
                                    action_id=action.id,
                                    item_id=item.id,
                                    item_title=item.title,
                                    item_url=item.url,
                                    triggered_at=datetime.now(),
                                    exit_code=code,
                                    output=output,
                                )
                            )

                            action.last_run = datetime.now()
                            action.last_output = output
                            action.last_exit_code = code
                            storage.update_action(action)

                            if code != 0:
                                errors.append(f"Action {action.name} failed with exit code {code}")
                        except Exception as e:
                            errors.append(f"Action execution error for {action.name}: {str(e)}")

        if not cron:
            result = {
                "checked_sources": len(sources),
                "triggered_rules": len(triggered),
                "errors": errors,
                "triggers": [
                    {
                        "rule": r["rule"].name,
                        "source": r["source"].identifier,
                        "item": r["item"].title,
                        "item_url": r["item"].url,
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
