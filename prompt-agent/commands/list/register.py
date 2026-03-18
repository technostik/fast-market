from __future__ import annotations

import click

from commands.base import CommandManifest
from common.cli.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("list")
    @click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
    @click.pass_context
    def list_cmd(ctx, fmt):
        """List all prompts."""
        from storage.store import PromptStore

        prompts = PromptStore().list_prompts()
        if fmt == "json":
            out(
                [
                    {
                        "name": p.name,
                        "description": p.description,
                        "provider": p.model_provider,
                        "model": p.model_name,
                    }
                    for p in prompts
                ],
                fmt,
            )
            return

        if not prompts:
            click.echo("No prompts found.")
            return
        for prompt in prompts:
            click.echo(f"\n{prompt.name}")
            if prompt.description:
                click.echo(f"  Description: {prompt.description}")
            if prompt.model_provider:
                click.echo(f"  Provider: {prompt.model_provider}")
            if prompt.model_name:
                click.echo(f"  Model: {prompt.model_name}")

    return CommandManifest(name="list", click_command=list_cmd)
