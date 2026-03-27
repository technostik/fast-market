from __future__ import annotations

import json

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir
from common.skill.skill import discover_skills


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("list")
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format",
    )
    def list_cmd(fmt):
        """List all available skills."""
        skills_dir = get_skills_dir()
        skills = discover_skills(skills_dir)

        if fmt == "json":
            click.echo(
                json.dumps(
                    [
                        {
                            "name": s.name,
                            "description": s.description,
                            "has_scripts": s.has_scripts,
                        }
                        for s in skills
                    ],
                    indent=2,
                )
            )
            return

        if not skills:
            click.echo(f"No skills found in {skills_dir}")
            return

        click.echo(f"Skills directory: {skills_dir}\n")
        for skill in skills:
            click.echo(f"  {skill.name}")
            if skill.description:
                click.echo(f"    Description: {skill.description}")
            if skill.has_scripts:
                click.echo("    Has executable scripts")

    return CommandManifest(name="list", click_command=list_cmd)
