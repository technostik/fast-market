from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("delete")
    @click.argument("name")
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation")
    def delete_cmd(name, force):
        """Delete a skill."""
        skill_path = get_skills_dir() / name
        if not skill_path.exists():
            click.echo(f"Error: Skill '{name}' not found", err=True)
            sys.exit(1)

        if not force:
            click.confirm(f"Delete skill '{name}'?", abort=True)

        import shutil

        shutil.rmtree(skill_path)
        click.echo(f"Deleted skill: {name}")

    return CommandManifest(name="delete", click_command=delete_cmd)
