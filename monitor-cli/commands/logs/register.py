from __future__ import annotations

import click
from datetime import datetime, timedelta

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("logs")
    @click.option("--since", help="Show/delete logs since (e.g., '1d', '1h', '30m', or ISO date)")
    @click.option("--before", help="Delete logs before (e.g., '7d', '2024-01-01')")
    @click.option("--rule-id", help="Filter by rule ID")
    @click.option("--source-id", help="Filter by source ID")
    @click.option("--action-id", help="Filter by action ID")
    @click.option("--meta-filter", "meta_filter", help="Filter by source metadata (key=value)")
    @click.option("--limit", type=int, default=100, help="Maximum number of logs to show")
    @click.option("--format", "fmt", type=click.Choice(["json", "text", "yaml"]), default="text")
    @click.option("--clean", is_flag=True, help="Delete matching logs instead of showing")
    @click.option(
        "--mismatch",
        "mismatch_only",
        is_flag=True,
        help="Show rule mismatch logs instead of trigger logs",
    )
    @click.pass_context
    def logs_cmd(
        ctx,
        since,
        before,
        rule_id,
        source_id,
        action_id,
        meta_filter,
        limit,
        fmt,
        clean,
        mismatch_only,
    ):
        """View or clean trigger history and rule mismatch logs."""
        storage = get_storage()

        since_dt = _parse_since(since) if since else None
        before_dt = _parse_since(before) if before else None

        if mismatch_only:
            if clean:
                deleted = storage.clean_rule_mismatch_logs(since=since_dt, before=before_dt)
                out_formatted(
                    {"deleted": deleted, "message": f"Deleted {deleted} mismatch log entries"}, fmt
                )
                return

            logs = storage.get_rule_mismatch_logs(
                since=since_dt,
                rule_id=rule_id,
                source_id=source_id,
                limit=limit,
            )

            formatted_logs = [
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

            out_formatted(formatted_logs, fmt)
            return

        if clean:
            deleted = storage.clean_trigger_logs(since=since_dt, before=before_dt)
            out_formatted({"deleted": deleted, "message": f"Deleted {deleted} log entries"}, fmt)
            return

        meta_key, meta_value = None, None
        if meta_filter:
            if "=" not in meta_filter:
                out_formatted({"error": "meta-filter must be key=value format"}, fmt)
                return
            meta_key, meta_value = meta_filter.split("=", 1)

        logs = storage.get_trigger_logs_with_metadata(
            since=since_dt,
            rule_id=rule_id,
            source_id=source_id,
            action_id=action_id,
            meta_key=meta_key,
            meta_value=meta_value,
            limit=limit,
        )

        formatted_logs = [
            {
                "id": log.id,
                "rule_id": log.rule_id,
                "source_id": log.source_id,
                "source_metadata": log.source_metadata,
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
