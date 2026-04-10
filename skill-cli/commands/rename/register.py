from __future__ import annotations

import sys

import click
import yaml

from commands.base import CommandManifest
from commands.params import SkillNameType
from common.core.paths import get_skills_dir


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("rename")
    @click.argument("old_name", type=SkillNameType())
    @click.argument("new_name")
    @click.option(
        "--force", "-f", is_flag=True, help="Skip confirmation if overwriting"
    )
    def rename_cmd(old_name, new_name, force):
        """Rename a skill."""
        old_path = get_skills_dir() / old_name

        if not old_path.exists():
            click.echo(f"Error: Skill '{old_name}' not found", err=True)
            sys.exit(1)

        new_path = get_skills_dir() / new_name

        if new_path.exists():
            if not force:
                click.confirm(
                    f"Skill '{new_name}' already exists. Overwrite?", abort=True
                )
            import shutil

            shutil.rmtree(new_path)

        import shutil

        shutil.move(str(old_path), str(new_path))

        # Update the name field in SKILL.md frontmatter
        skill_md = new_path / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        frontmatter = yaml.safe_load(parts[1])
                        frontmatter["name"] = new_name
                        new_frontmatter = yaml.dump(
                            frontmatter, default_flow_style=False, allow_unicode=True
                        )
                        new_content = f"---\n{new_frontmatter}---{parts[2]}"
                        skill_md.write_text(new_content, encoding="utf-8")
                    except Exception as e:
                        click.echo(
                            f"Warning: Could not update SKILL.md frontmatter: {e}",
                            err=True,
                        )

        click.echo(f"Renamed skill: {old_name} -> {new_name}")

    return CommandManifest(name="rename", click_command=rename_cmd)
