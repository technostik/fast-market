from __future__ import annotations

import sys
from pathlib import Path

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("create")
    def create_group():
        """Create a new skill."""
        pass

    @create_group.command("name")
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

    @create_group.command("auto-from-session")
    @click.argument("session_file", type=click.Path(exists=True))
    @click.option(
        "--skill-name",
        "-n",
        default=None,
        help="Skill name (auto-generated if omitted)",
    )
    def auto_from_session_cmd(session_file, skill_name):
        """Create a skill draft from a session file."""
        from core.session_to_skill import create_skill_from_session

        session_path = Path(session_file)
        create_skill_from_session(session_path, skill_name)

    @create_group.command("from-description")
    @click.argument("description", required=False)
    @click.option(
        "--skill-name",
        "-n",
        default=None,
        help="Skill name (auto-generated if omitted)",
    )
    def from_description_cmd(description, skill_name):
        """Create a skill from a task description."""
        from core.description_to_skill import create_skill_from_description

        if not description:
            from core.repl import prompt_free_text

            description = prompt_free_text("Enter task description: ")
            while not description:
                description = prompt_free_text("Enter task description: ")

        create_skill_from_description(description, skill_name)

    return CommandManifest(name="create", click_command=create_group)
