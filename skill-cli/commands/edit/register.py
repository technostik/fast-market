from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from commands.params import SkillNameType, SkillFileType
from common.cli.helpers import open_editor
from common.core.paths import get_skills_dir


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("edit")
    @click.argument("skill_name", type=SkillNameType())
    @click.argument("file", required=False, default=None, type=SkillFileType())
    @click.option(
        "--create",
        "-c",
        is_flag=True,
        help="Create FILE if it does not exist",
    )
    @click.option(
        "--learn",
        "-l",
        is_flag=True,
        help="Edit LEARN.md instead of SKILL.md or FILE",
    )
    @click.option(
        "--shell",
        "-s",
        is_flag=True,
        help="Edit scripts/run.sh instead of SKILL.md or FILE",
    )
    def edit_cmd(skill_name, file, create, learn, shell):
        """Edit a skill file in the default editor."""
        skills_dir = get_skills_dir()
        skill_dir = skills_dir / skill_name

        if not skill_dir.exists():
            click.echo(f"Error: Skill '{skill_name}' not found", err=True)
            sys.exit(1)

        if learn:
            target = skill_dir / "LEARN.md"
        elif shell:
            target = skill_dir / "scripts" / "run.sh"
        elif file is None:
            target = skill_dir / "SKILL.md"
        else:
            target = skill_dir / file

        skill_dir_resolved = skill_dir.resolve()
        target_resolved = target.resolve()
        if not str(target_resolved).startswith(str(skill_dir_resolved)):
            click.echo("Error: path must be within skill directory", err=True)
            sys.exit(1)

        if not target_resolved.exists():
            if not create:
                click.echo(
                    f"Error: '{target.name}' not found in skill '{skill_name}'.\n"
                    "Hint: use --create to create it",
                    err=True,
                )
                sys.exit(1)

            target_resolved.parent.mkdir(parents=True, exist_ok=True)
            if target_resolved.suffix == ".sh":
                target_resolved.write_text(
                    "#!/usr/bin/env bash\nset -euo pipefail\n\n",
                    encoding="utf-8",
                )
                target_resolved.chmod(target_resolved.stat().st_mode | 0o111)
            else:
                target_resolved.touch()
            click.echo(f"Created: {target_resolved}")

        open_editor(target_resolved)

    return CommandManifest(name="edit", click_command=edit_cmd)
