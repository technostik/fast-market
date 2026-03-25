from __future__ import annotations

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("validate")
    @click.option(
        "--format", "fmt", type=click.Choice(["text", "json"]), default="text"
    )
    @click.pass_context
    def validate_cmd(ctx, fmt):
        """Validate all prompt files (check frontmatter is valid YAML)."""
        from storage.store import PromptStore

        store = PromptStore()
        result = store.validate_all_prompts()

        if fmt == "json":
            click.echo(click.style("ERROR: JSON output not yet implemented", fg="red"))
            return

        if not result["errors"]:
            click.echo(f"✓ All {len(result['valid'])} prompts are valid.")
            return

        click.echo(f"✗ Found {len(result['errors'])} invalid prompt(s):\n")
        for err in result["errors"]:
            click.echo(f"  {err['file']}")
            click.echo(f"    {err['error']}\n")

    return CommandManifest(name="validate", click_command=validate_cmd)
