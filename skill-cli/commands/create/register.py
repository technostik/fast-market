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

    @create_group.command("auto-from-session")
    @click.argument("session_file", type=click.Path(exists=True))
    @click.option(
        "--name",
        "-n",
        default=None,
        help="Skill name (auto-generated if omitted)",
    )
    def auto_from_session_cmd(session_file, name):
        """Create a skill draft from a session file."""
        from core.session_to_skill import create_skill_from_session

        session_path = Path(session_file)
        create_skill_from_session(session_path, name)

    @create_group.command("from-description")
    @click.argument("description", required=False)
    @click.option(
        "--name",
        "-n",
        default=None,
        help="Skill name (auto-generated if omitted)",
    )
    def from_description_cmd(description, name):
        """Create a skill from a task description."""
        from core.description_to_skill import create_skill_from_description

        if not description:
            from core.repl import prompt_free_text

            description = prompt_free_text("Enter task description: ")
            while not description:
                description = prompt_free_text("Enter task description: ")

        create_skill_from_description(description, name)

    return CommandManifest(name="create", click_command=create_group)
