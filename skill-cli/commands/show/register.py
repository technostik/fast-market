from __future__ import annotations

import sys

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
    @click.option(
        "--run",
        "-r",
        "show_run",
        is_flag=True,
        help="Show the run entry (run: frontmatter or scripts/run.sh)",
    )
    def show_cmd(name, learn, show_run):
        """Show skill details."""
        if learn and show_run:
            click.echo("Error: --learn and --run are mutually exclusive", err=True)
            sys.exit(1)

        skill_path = get_skills_dir() / name
        if not skill_path.exists():
            click.echo(f"Error: Skill '{name}' not found", err=True)
            return

        skill = Skill.from_path(skill_path)
        if not skill:
            click.echo(f"Error: '{name}' is not a valid skill", err=True)
            return

        if show_run:
            if skill.run:
                click.echo(skill.run)
            else:
                run_sh = skill_path / "scripts" / "run.sh"
                if run_sh.exists():
                    click.echo(run_sh.read_text(encoding="utf-8"))
                else:
                    click.echo("Error: No run entry found", err=True)
                    sys.exit(1)
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
