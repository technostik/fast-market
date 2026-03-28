from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from commands.completion import PromptNameParamType


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("edit")
    @click.argument("name", type=PromptNameParamType())
    @click.pass_context
    def edit_cmd(ctx, name):
        """Edit a prompt in the default editor."""
        from common.cli.helpers import open_editor
        from storage.store import PromptStore

        store = PromptStore()
        file_path = store.get_prompt_file_path(name)

        if not file_path or not file_path.exists():
            click.echo(f"Prompt not found: {name}", err=True)
            sys.exit(1)

        open_editor(file_path)

        try:
            store.validate_prompt(name)
        except ValueError as e:
            click.echo(f"✗ Prompt file is corrupted after edit: {e}", err=True)
            sys.exit(1)

        click.echo(f"✓ Edited prompt: {name}")

    return CommandManifest(name="edit", click_command=edit_cmd)
