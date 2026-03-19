from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir
from core.skill import Skill, discover_skills


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("skill")
    def skill_group():
        """Manage skills for agentic task execution."""
        pass

    @skill_group.command("list")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format",
    )
    def list_skills(fmt):
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

    @skill_group.command("path")
    def show_path():
        """Show the skills directory path."""
        click.echo(get_skills_dir())

    @skill_group.command("create")
    @click.argument("name")
    @click.option("--description", "-d", help="Skill description")
    @click.option("--with-scripts", is_flag=True, help="Create scripts directory")
    def create_skill(name, description, with_scripts):
        """Create a new skill scaffold."""
        skills_dir = get_skills_dir()
        skill_path = skills_dir / name

        if skill_path.exists():
            click.echo(f"Error: Skill '{name}' already exists", err=True)
            sys.exit(1)

        skill_path.mkdir(parents=True, exist_ok=True)

        template = f"""---
name: {name}
description: {description or "No description provided"}
---

# {name} Skill

## When to use this skill
Describe when this skill should be used.

## Instructions
Provide step-by-step instructions for using this skill.

## Examples
Include examples of how to use this skill.
"""
        (skill_path / "SKILL.md").write_text(template, encoding="utf-8")

        if with_scripts:
            (skill_path / "scripts").mkdir()
            (skill_path / "scripts" / "README.md").write_text(
                "# Scripts Directory\n\nPlace executable scripts here.\n"
            )

        click.echo(f"Created skill: {name} at {skill_path}")

    @skill_group.command("show")
    @click.argument("name")
    def show_skill(name):
        """Show skill details."""
        skill_path = get_skills_dir() / name
        if not skill_path.exists():
            click.echo(f"Error: Skill '{name}' not found", err=True)
            sys.exit(1)

        skill = Skill.from_path(skill_path)
        if not skill:
            click.echo(f"Error: '{name}' is not a valid skill", err=True)
            sys.exit(1)

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

    @skill_group.command("delete")
    @click.argument("name")
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation")
    def delete_skill(name, force):
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

    return CommandManifest(name="skill", click_command=skill_group)
