from __future__ import annotations

from datetime import datetime, timedelta

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("logs")
    @click.option(
        "--since", help="Show logs since (e.g., '1d', '1h', '30m', or ISO date)"
    )
    @click.option("--rule-id", help="Filter by rule ID")
    @click.option("--source-id", help="Filter by source ID")
    @click.option(
        "--limit", type=int, default=100, help="Maximum number of logs to show"
    )
    @click.option(
        "--format", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def logs_cmd(ctx, since, rule_id, source_id, limit, fmt):
        """View trigger history."""
        storage = get_storage()

        since_dt = None
        if since:
            since_dt = _parse_since(since)

        logs = storage.get_trigger_logs(
            since=since_dt, rule_id=rule_id, source_id=source_id, limit=limit
        )

        formatted_logs = [
            {
                "id": log.id,
                "rule_id": log.rule_id,
                "source_id": log.source_id,
                "action_id": log.action_id,
                "item_id": log.item_id,
                "item_title": log.item_title,
                "item_url": log.item_url,
                "triggered_at": log.triggered_at.isoformat(),
                "exit_code": log.exit_code,
                "output": log.output[:500]
                if log.output and len(log.output) > 500
                else log.output,
            }
            for log in logs
        ]

        out_formatted(formatted_logs, fmt)

    return CommandManifest(
        name="logs",
        click_command=logs_cmd,
    )


def _parse_since(since: str) -> datetime:
    """Parse time string like '1d', '1h', '30m' or ISO date."""
    now = datetime.now()

    if since.endswith("d"):
        days = int(since[:-1])
        return now - timedelta(days=days)
    elif since.endswith("h"):
        hours = int(since[:-1])
        return now - timedelta(hours=hours)
    elif since.endswith("m"):
        minutes = int(since[:-1])
        return now - timedelta(minutes=minutes)
    else:
        try:
            return datetime.fromisoformat(since)
        except ValueError:
            return now - timedelta(days=1)
