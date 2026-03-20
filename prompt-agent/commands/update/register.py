from __future__ import annotations

import sys
from pathlib import Path

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("update")
    @click.argument("name")
    @click.option("--content", "-c", default=None, help="New prompt template content")
    @click.option(
        "--from-file",
        "-f",
        type=click.Path(exists=True),
        default=None,
        help="Load content from file",
    )
    @click.option("--description", "-d", default=None, help="New description")
    @click.option("--provider", "-P", default=None, help="Default provider")
    @click.option("--model", "-m", default=None, help="Default model")
    @click.option("--temperature", "-T", type=float, default=None)
    @click.option("--max-tokens", "-M", type=int, default=None)
    @click.pass_context
    def update_cmd(
        ctx,
        name,
        content,
        from_file,
        description,
        provider,
        model,
        temperature,
        max_tokens,
    ):
        """Update a prompt template."""
        from storage.store import PromptStore

        updates: dict[str, object] = {}
        if from_file:
            updates["content"] = Path(from_file).read_text(encoding="utf-8")
        elif content is not None:
            updates["content"] = content
        if description is not None:
            updates["description"] = description
        if provider is not None:
            updates["model_provider"] = provider
        if model is not None:
            updates["model_name"] = model
        if temperature is not None:
            updates["temperature"] = temperature
        if max_tokens is not None:
            updates["max_tokens"] = max_tokens
        if not updates:
            click.echo("Error: no updates provided", err=True)
            sys.exit(1)

        store = PromptStore()
        try:
            updated = store.update_prompt(name, **updates)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        if not updated:
            click.echo(f"Prompt not found: {name}", err=True)
            sys.exit(1)
        click.echo(f"✓ Prompt updated: {name}")

    return CommandManifest(name="update", click_command=update_cmd)
