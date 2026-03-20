from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("create")
    @click.argument("name")
    @click.option("--content", "-c", help="Prompt template content")
    @click.option(
        "--from-file", "-f", type=click.Path(exists=True), help="Load content from file"
    )
    @click.option("--description", "-d", default="", help="Description")
    @click.option("--provider", "-P", default="", help="Default provider")
    @click.option("--model", "-m", default="", help="Default model")
    @click.option("--temperature", "-T", type=float, default=0.7)
    @click.option("--max-tokens", "-M", type=int, default=2048)
    @click.pass_context
    def create_cmd(
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
        """Create a new prompt template."""
        from core.models import Prompt
        from storage.store import PromptStore

        if from_file:
            content = Path(from_file).read_text(encoding="utf-8")
        elif not content:
            click.echo("Error: Must provide --content or --from-file", err=True)
            sys.exit(1)

        prompt = Prompt(
            name=name,
            content=content,
            description=description,
            model_provider=provider,
            model_name=model,
            temperature=temperature,
            max_tokens=max_tokens,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        store = PromptStore()
        try:
            store.create_prompt(prompt)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        click.echo(f"✓ Prompt created: {name}")

    return CommandManifest(name="create", click_command=create_cmd)
