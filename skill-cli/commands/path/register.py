from __future__ import annotations

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("path")
    def path_cmd():
        """Show the skills directory path."""
        click.echo(get_skills_dir())

    return CommandManifest(name="path", click_command=path_cmd)
