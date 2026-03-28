from __future__ import annotations

import sys

import click
import yaml

from commands.base import CommandManifest
from common.core.yaml_utils import dump_yaml


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("logs")
    @click.option(
        "--limit", "-n", type=int, default=50, help="Number of entries to show"
    )
    @click.option(
        "--format",
        "-f",
        type=click.Choice(["table", "json", "yaml"]),
        default="table",
        help="Output format",
    )
    @click.option("--clean", is_flag=True, help="Truncate execution log")
    @click.option("--yes", is_flag=True, help="Skip confirmation for --clean")
    @click.pass_context
    def logs_cmd(ctx, limit, format, clean, yes):
        """Display execution history."""
        from storage.store import PromptStore

        store = PromptStore()

        if clean:
            if not yes and not click.confirm("Truncate execution log?"):
                click.echo("Cancelled.")
                return
            deleted = store.truncate_executions()
            click.echo(f"✓ Deleted {deleted} execution log entries.")
            return

        entries = store.list_executions(limit)

        if format == "json":
            import json

            click.echo(json.dumps(entries, indent=2, default=str))
            return

        if format == "yaml":
            click.echo(dump_yaml(entries, sort_keys=False))
            return

        if not entries:
            click.echo("No execution logs found.")
            return

        for entry in entries:
            timestamp = entry.get("timestamp", "")
            prompt_name = entry.get("prompt_name", "<unknown>")
            model = entry.get("model_name", "")
            output = entry.get("output", "")
            preview = output[:50] + "..." if len(output) > 50 else output
            click.echo(f"{timestamp} | {prompt_name} | {model} | {preview}")

    return CommandManifest(name="logs", click_command=logs_cmd)
