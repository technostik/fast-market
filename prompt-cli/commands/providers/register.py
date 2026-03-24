from __future__ import annotations

import click

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.config import load_tool_config


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("providers")
    @click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
    @click.pass_context
    def providers_cmd(ctx, fmt):
        """List available/configured LLM providers."""
        config = load_tool_config("prompt")
        configured = config.get("providers", {}) if isinstance(config.get("providers", {}), dict) else {}
        data = []
        for name, manifest in sorted(plugin_manifests.items()):
            settings = configured.get(name, {})
            data.append(
                {
                    "name": name,
                    "configured": name in configured,
                    "default": config.get("default_provider") == name,
                    "default_model": settings.get("default_model", ""),
                    "base_url": settings.get("base_url", ""),
                }
            )
        if fmt == "json":
            out(data, fmt)
            return
        if not data:
            click.echo("No providers discovered.")
            return
        for item in data:
            marker = " (default)" if item["default"] else ""
            state = "configured" if item["configured"] else "not configured"
            click.echo(f"{item['name']}{marker}: {state}")
            if item["default_model"]:
                click.echo(f"  Default model: {item['default_model']}")
            if item["base_url"]:
                click.echo(f"  Base URL: {item['base_url']}")

    return CommandManifest(name="providers", click_command=providers_cmd)
