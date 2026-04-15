from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from commands.completion import PromptNameParamType


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("edit")
    @click.argument("name", type=PromptNameParamType(), required=False)
    @click.option(
        "--content",
        "content_from_option",
        is_flag=True,
        help="Read new content from stdin (or use - to read from stdin as name)",
    )
    @click.pass_context
    def edit_cmd(ctx, name, content_from_option):
        """Edit a prompt in the default editor."""
        from common.cli.helpers import open_editor
        from storage.store import PromptStore

        store = PromptStore()

        # Handle stdin-based content update
        if content_from_option:
            if name is None:
                click.echo("Error: Prompt name required when using --content", err=True)
                sys.exit(1)
            if sys.stdin.isatty():
                click.echo("Error: No content provided via stdin", err=True)
                sys.exit(1)
            new_content = sys.stdin.read()
            success = store.update_prompt(name, content=new_content)
            if not success:
                click.echo(f"Prompt not found: {name}", err=True)
                sys.exit(1)
            click.echo(f"✓ Updated content for prompt: {name}")
            return

        # Handle "-" as name to read from stdin
        if name == "-":
            if sys.stdin.isatty():
                click.echo(
                    "Error: Prompt name required (use - to read from stdin)", err=True
                )
                sys.exit(1)
            name = sys.stdin.read().strip()
            if not name:
                click.echo("Error: Empty prompt name from stdin", err=True)
                sys.exit(1)

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
