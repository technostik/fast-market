from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from core.substitution import extract_placeholders


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("get")
    @click.argument("name")
    @click.option(
        "--format", "fmt", type=click.Choice(["text", "json"]), default="text"
    )
    @click.pass_context
    def get_cmd(ctx, name, fmt):
        """Show a stored prompt."""
        from storage.store import PromptStore

        store = PromptStore()
        prompt = store.get_prompt(name)
        if not prompt:
            click.echo(f"Prompt not found: {name}", err=True)
            sys.exit(1)

        payload = {
            "name": prompt.name,
            "description": prompt.description,
            "content": prompt.content,
            "placeholders": extract_placeholders(prompt.content),
            "provider": prompt.model_provider,
            "model": prompt.model_name,
            "temperature": prompt.temperature,
            "max_tokens": prompt.max_tokens,
        }
        if fmt == "json":
            import json

            click.echo(json.dumps(payload, indent=2))
            return

        click.echo(prompt.name)
        if prompt.description:
            click.echo(f"Description: {prompt.description}")
        click.echo(f"Placeholders: {', '.join(payload['placeholders']) or '(none)'}")
        if prompt.model_provider:
            click.echo(f"Provider: {prompt.model_provider}")
        if prompt.model_name:
            click.echo(f"Model: {prompt.model_name}")
        click.echo("\n---\n")
        click.echo(prompt.content)

    return CommandManifest(name="get", click_command=get_cmd)
