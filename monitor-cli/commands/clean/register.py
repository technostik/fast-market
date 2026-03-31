from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
from commands.params import RuleIdType, SourceIdType, ActionIdType
from commands.logs.register import _parse_since


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("clean")
    @click.option("--since", help="Delete logs since (e.g., '1d', '1h', '30m', or ISO date)")
    @click.option("--before", help="Delete logs before (e.g., '7d', '2024-01-01')")
    @click.option("--rule-id", type=RuleIdType(), help="Delete logs for specific rule ID")
    @click.option("--source-id", type=SourceIdType(), help="Delete logs for specific source ID")
    @click.option("--action-id", type=ActionIdType(), help="Delete logs for specific action ID")
    @click.option(
        "--mismatch",
        "mismatch_only",
        is_flag=True,
        help="Clean rule mismatch logs instead of trigger logs",
    )
    @click.option("--format", "fmt", type=click.Choice(["json", "text", "yaml"]), default="text")
    @click.pass_context
    def clean_cmd(
        ctx,
        since,
        before,
        rule_id,
        source_id,
        action_id,
        mismatch_only,
        fmt,
    ):
        """Clean trigger history and rule mismatch logs."""
        storage = get_storage()

        since_dt = _parse_since(since) if since else None
        before_dt = _parse_since(before) if before else None

        if not since_dt and not before_dt and not rule_id and not source_id and not action_id:
            out_formatted(
                {
                    "error": "Must specify at least one filter: --since, --before, --rule-id, --source-id, or --action-id"
                },
                fmt,
            )
            return

        if mismatch_only:
            if rule_id or source_id or action_id:
                out_formatted(
                    {
                        "error": "Filtering by rule-id, source-id, or action-id is not supported for mismatch logs"
                    },
                    fmt,
                )
                return

            deleted = storage.clean_rule_mismatch_logs(since=since_dt, before=before_dt)
            out_formatted(
                {"deleted": deleted, "message": f"Deleted {deleted} mismatch log entries"}, fmt
            )
            return

        if rule_id or source_id or action_id:
            out_formatted(
                {
                    "error": "Filtering by rule-id, source-id, or action-id requires --since or --before"
                },
                fmt,
            )
            return

        deleted = storage.clean_trigger_logs(since=since_dt, before=before_dt)
        out_formatted({"deleted": deleted, "message": f"Deleted {deleted} log entries"}, fmt)

    return CommandManifest(
        name="clean",
        click_command=clean_cmd,
    )
