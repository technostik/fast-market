from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("create")
    @click.argument("name")
    @click.option("--description", "-d", help="Skill description")
    @click.option("--with-scripts", "-s", is_flag=True, help="Create scripts directory")
    def create_cmd(name, description, with_scripts):
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

    return CommandManifest(name="create", click_command=create_cmd)
