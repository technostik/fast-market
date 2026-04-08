from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.params import SkillNameType
from common.core.paths import get_skills_dir
from core.skill import Skill


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("show")
    @click.argument("name", type=SkillNameType())
    @click.option(
        "--learn",
        "-l",
        is_flag=True,
        help="Show LEARN.md instead of SKILL.md",
    )
    def show_cmd(name, learn):
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

        if learn:
            learned_path = skill_path / "LEARN.md"
            if not learned_path.exists():
                click.echo(f"Error: LEARN.md not found in skill '{name}'", err=True)
                return
            click.echo("\n  --- LEARN.md ---")
            content = learned_path.read_text(encoding="utf-8")
            click.echo(content[:500] + ("..." if len(content) > 500 else ""))
        else:
            click.echo("\n  --- SKILL.md ---")
            content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
            click.echo(content[:500] + ("..." if len(content) > 500 else ""))

            if skill.has_scripts:
                click.echo("\n  Scripts:")
                for script in (skill_path / "scripts").iterdir():
                    if script.is_file() and not script.name.startswith("."):
                        click.echo(f"    - {script.name}")

    return CommandManifest(name="show", click_command=show_cmd)
