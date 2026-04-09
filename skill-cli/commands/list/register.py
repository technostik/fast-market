from __future__ import annotations

import json

import click

from commands.base import CommandManifest
from common.core.paths import get_skills_dir
from core.skill import discover_skills


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
                            "mode": s.get_execution_mode(),
                            "has_scripts": s.has_scripts,
                            "health_issues": s.health_check(),
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
            mode = skill.get_execution_mode()
            issues = skill.health_check()
            status = ""
            if issues:
                status = f" ⚠ {', '.join(issues)}"
            
            click.echo(f"  {skill.name} [{mode}]{status}")
            if skill.description:
                click.echo(f"    Description: {skill.description}")
            if skill.has_scripts:
                scripts_dir = skill.path / "scripts"
                script_files = [p.name for p in scripts_dir.iterdir() if p.is_file()]
                if script_files:
                    click.echo(f"    Scripts: {', '.join(script_files)}")

    return CommandManifest(name="list", click_command=list_cmd)
