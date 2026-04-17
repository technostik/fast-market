from __future__ import annotations

import click

from commands.base import CommandManifest
from common.cli.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("list")
    @click.option(
        "--format", "fmt", type=click.Choice(["text", "json"]), default="text"
    )
    @click.option("--long", "-l", is_flag=True, help="Show full details")
    @click.option(
        "--names-only", is_flag=True, help="Output only prompt names, one per line"
    )
    @click.option(
        "--with-filename",
        is_flag=True,
        help="Output prompt name with filename (name:filename)",
    )
    @click.pass_context
    def list_cmd(ctx, fmt, long, names_only, with_filename):
        """List all prompts."""
        from storage.store import PromptStore

        prompts = PromptStore().list_prompts()

        if with_filename:
            for p in prompts:
                path = PromptStore().get_prompt_file_path(p.name)
                filename = path.name if path else f"{p.name}.md"
                click.echo(f"{p.name}:{filename}")
            return

        if names_only:
            for p in prompts:
                click.echo(p.name)
            return

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

        if long:
            for prompt in prompts:
                click.echo(f"\n{prompt.name}")
                if prompt.description:
                    click.echo(f"  Description: {prompt.description}")
                if prompt.model_provider:
                    click.echo(f"  Provider: {prompt.model_provider}")
                if prompt.model_name:
                    click.echo(f"  Model: {prompt.model_name}")
        else:
            for prompt in prompts:
                desc = f" - {prompt.description}" if prompt.description else ""
                click.echo(f"{prompt.name}{desc}")

    return CommandManifest(name="list", click_command=list_cmd)
