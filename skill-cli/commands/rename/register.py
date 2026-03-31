from __future__ import annotations

import sys

import click
import yaml

from commands.base import CommandManifest
from common.core.paths import get_skills_dir


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("rename")
    @click.argument("old_name")
    @click.argument("new_name")
    @click.option(
        "--force", "-f", is_flag=True, help="Skip confirmation if overwriting"
    )
    def rename_cmd(old_name, new_name, force):
        """Rename a skill."""
        old_path = get_skills_dir() / old_name

        if not old_path.exists():
            click.echo(f"Error: Skill '{old_name}' not found", err=True)
            sys.exit(1)

        new_path = get_skills_dir() / new_name

        if new_path.exists():
            if not force:
                click.confirm(
                    f"Skill '{new_name}' already exists. Overwrite?", abort=True
                )
            import shutil

            shutil.rmtree(new_path)

        import shutil

        shutil.move(str(old_path), str(new_path))

        click.echo(f"Renamed skill: {old_name} -> {new_name}")

    return CommandManifest(name="rename", click_command=rename_cmd)
