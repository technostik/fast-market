from __future__ import annotations

import sys

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("delete")
    @click.argument("name")
    @click.option("--yes", is_flag=True, default=False, help="Delete without confirmation")
    @click.pass_context
    def delete_cmd(ctx, name, yes):
        """Delete a prompt."""
        from storage.store import PromptStore

        if not yes and not click.confirm(f"Delete prompt '{name}'?", default=False):
            click.echo("Cancelled.")
            return

        deleted = PromptStore().delete_prompt(name)
        if not deleted:
            click.echo(f"Prompt not found: {name}", err=True)
            sys.exit(1)
        click.echo(f"✓ Prompt deleted: {name}")

    return CommandManifest(name="delete", click_command=delete_cmd)
