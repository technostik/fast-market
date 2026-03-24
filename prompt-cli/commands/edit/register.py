from __future__ import annotations

import sys

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("edit")
    @click.argument("name")
    @click.pass_context
    def edit_cmd(ctx, name):
        """Edit a prompt in the default editor."""
        from commands.setup import run_default_editor
        from storage.store import PromptStore

        store = PromptStore()
        file_path = store.get_prompt_file_path(name)

        if not file_path or not file_path.exists():
            click.echo(f"Prompt not found: {name}", err=True)
            sys.exit(1)

        run_default_editor(file_path)
        click.echo(f"✓ Edited prompt: {name}")

    return CommandManifest(name="edit", click_command=edit_cmd)
