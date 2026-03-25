from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted

_follow_running = False


def _signal_handler(signum, frame):
    global _follow_running
    _follow_running = False


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
    @click.option(
        "--follow",
        "-f",
        is_flag=True,
        help="Follow logs in real-time (like tail -f)",
    )
    @click.option(
        "--interval",
        default="1s",
        help="Polling interval for --follow (e.g., '1s', '500ms', '2s')",
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
        follow,
        interval,
    ):
        """View or clean trigger history and rule mismatch logs."""
        storage = get_storage()

        since_dt = _parse_since(since) if since else None
        before_dt = _parse_since(before) if before else None

        if follow:
            _follow_logs(
                storage=storage,
                rule_id=rule_id,
                source_id=source_id,
                action_id=action_id,
                meta_filter=meta_filter,
                interval=interval,
                mismatch=mismatch_only,
            )
            return

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


def _parse_interval(interval_str: str) -> float:
    """Parse interval string like '1s', '500ms', '2s' to seconds."""
    interval_str = interval_str.strip().lower()
    if interval_str.endswith("ms"):
        return int(interval_str[:-2]) / 1000.0
    elif interval_str.endswith("s"):
        return int(interval_str[:-1])
    elif interval_str.endswith("m"):
        return int(interval_str[:-1]) * 60
    else:
        return int(interval_str)


def _follow_logs(
    storage,
    rule_id: str | None,
    source_id: str | None,
    action_id: str | None,
    meta_filter: str | None,
    interval: str,
    mismatch: bool,
) -> None:
    global _follow_running

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    interval_secs = _parse_interval(interval)

    meta_key, meta_value = None, None
    if meta_filter:
        if "=" not in meta_filter:
            click.echo("Error: meta-filter must be key=value format", err=True)
            return
        meta_key, meta_value = meta_filter.split("=", 1)

    last_timestamp: datetime | None = None
    seen_log_ids: set[str] = set()
    _follow_running = True

    min_ts = datetime.min.replace(tzinfo=timezone.utc)

    click.echo("Following logs... (Ctrl+C to stop)", err=True)

    while _follow_running:
        since_dt = None
        if last_timestamp:
            since_dt = last_timestamp

        if mismatch:
            logs = storage.get_rule_mismatch_logs(
                since=since_dt,
                rule_id=rule_id,
                source_id=source_id,
                limit=100,
            )
        else:
            logs = storage.get_trigger_logs_with_metadata(
                since=since_dt,
                rule_id=rule_id,
                source_id=source_id,
                action_id=action_id,
                meta_key=meta_key,
                meta_value=meta_value,
                limit=100,
            )

        if logs:
            for log in logs:
                if log.id in seen_log_ids:
                    continue
                seen_log_ids.add(log.id)

                if mismatch:
                    _print_mismatch_log(log)
                else:
                    _print_trigger_log(log)

                if log.triggered_at > (last_timestamp or min_ts):
                    last_timestamp = log.triggered_at

        time.sleep(interval_secs)


def _print_trigger_log(log) -> None:
    timestamp = log.triggered_at.strftime("%Y-%m-%d %H:%M:%S")
    exit_code = log.exit_code if log.exit_code is not None else "-"

    color = ""
    reset = ""
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        if exit_code == 0:
            color = "\033[92m"
        elif exit_code != 0 and exit_code != "-":
            color = "\033[91m"

    title = log.item_title[:60] + "..." if len(log.item_title) > 60 else log.item_title

    click.echo(
        f"{color}{timestamp}{reset} | rule={log.rule_id} | source={log.source_id} | "
        f"action={log.action_id} | exit={color}{exit_code}{reset} | {title}"
    )


def _print_mismatch_log(log) -> None:
    timestamp = log.evaluated_at.strftime("%Y-%m-%d %H:%M:%S")
    title = log.item_title[:60] + "..." if len(log.item_title) > 60 else log.item_title

    color = ""
    reset = ""
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        color = "\033[93m"

    click.echo(
        f"{color}{timestamp}{reset} | rule={log.rule_id} | source={log.source_id} | "
        f"MISMATCH | {title}"
    )
