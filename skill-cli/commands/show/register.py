from __future__ import annotations

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir
from common.skill.skill import Skill


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("show")
    @click.argument("name")
    def show_cmd(name):
        """Show skill details."""
        skill_path = get_skills_dir() / name
        if not skill_path.exists():
            click.echo(f"Error: Skill '{name}' not found", err=True)
            return

        skill = Skill.from_path(skill_path)
        if not skill:
            click.echo(f"Error: '{name}' is not a valid skill", err=True)
            return

        click.echo(f"  {skill.name}")
        click.echo(f"    Path: {skill.path}")
        if skill.description:
            click.echo(f"    Description: {skill.description}")

        click.echo("\n  --- SKILL.md ---")
        content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
        click.echo(content[:500] + ("..." if len(content) > 500 else ""))

        if skill.has_scripts:
            click.echo("\n  Scripts:")
            for script in (skill_path / "scripts").iterdir():
                if script.is_file() and not script.name.startswith("."):
                    click.echo(f"    - {script.name}")

    return CommandManifest(name="show", click_command=show_cmd)
