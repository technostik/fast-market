from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("status")
    @click.option(
        "--format", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def status_cmd(ctx, fmt):
        """Show monitor health and statistics."""
        storage = get_storage()

        stats = storage.get_stats()

        sources = storage.get_all_sources()
        rules = storage.get_all_rules()
        actions = storage.get_all_actions()

        source_details = [
            {
                "id": s.id,
                "plugin": s.plugin,
                "identifier": s.identifier,
                "last_check": s.last_check.isoformat() if s.last_check else None,
                "last_item_id": s.last_item_id,
            }
            for s in sources
        ]

        rule_details = [
            {
                "id": r.id,
                "name": r.name,
                "action_ids": r.action_ids,
                "conditions_count": _count_conditions(r.conditions),
            }
            for r in rules
        ]

        action_details = [
            {
                "id": a.id,
                "name": a.name,
                "last_run": a.last_run.isoformat() if a.last_run else None,
                "last_exit_code": a.last_exit_code,
            }
            for a in actions
        ]

        result = {
            "statistics": stats,
            "sources": source_details,
            "rules": rule_details,
            "actions": action_details,
        }

        out_formatted(result, fmt)

    return CommandManifest(
        name="status",
        click_command=status_cmd,
    )


def _count_conditions(conditions: dict) -> int:
    """Count the number of leaf conditions in a rule."""
    count = 0
    if "all" in conditions:
        for c in conditions["all"]:
            count += _count_conditions(c)
    elif "any" in conditions:
        for c in conditions["any"]:
            count += _count_conditions(c)
    else:
        count = 1
    return count
