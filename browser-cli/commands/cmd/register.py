from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click
import yaml
from click.shell_completion import CompletionItem

from commands.base import CommandManifest
from common.cli.helpers import open_editor
from common.core.paths import get_browser_cmds_dir
from core.browser_cmd import BrowserCmd, _COMMAND_TEMPLATE, discover_browser_cmds


class _CmdNameType(click.ParamType):
    name = "CMD_NAME"

    def shell_complete(self, ctx, param, incomplete):
        try:
            cmds = discover_browser_cmds(get_browser_cmds_dir())
        except Exception:
            return []
        return [
            CompletionItem(c.name, help=c.description or "")
            for c in cmds
            if c.name.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("cmd")
    def cmd_group():
        """Manage stored browser commands."""
        pass

    @cmd_group.command("list")
    @click.option(
        "--format", "-F", "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format.",
    )
    def list_cmd(fmt):
        """List all stored browser commands."""
        cmds_dir = get_browser_cmds_dir()
        cmds = discover_browser_cmds(cmds_dir)

        if fmt == "json":
            click.echo(json.dumps(
                [
                    {
                        "name": c.name,
                        "description": c.description,
                        "parameters": c.parameters,
                        "instruction_count": len(c.get_instructions()),
                    }
                    for c in cmds
                ],
                indent=2,
            ))
            return

        if not cmds:
            click.echo(f"No browser commands found in {cmds_dir}")
            return

        click.echo(f"Browser commands directory: {cmds_dir}\n")
        for cmd in cmds:
            n_inst = len(cmd.get_instructions())
            click.echo(f"  {cmd.name}  [{n_inst} instruction(s)]")
            if cmd.description:
                click.echo(f"    {cmd.description}")
            if cmd.parameters:
                pnames = ", ".join(p.get("name", "?") for p in cmd.parameters)
                click.echo(f"    Parameters: {pnames}")

    @cmd_group.command("create")
    @click.argument("name")
    @click.option("--description", "-d", default="", help="Short description of what the command does.")
    @click.option("--no-edit", is_flag=True, help="Create without opening an editor.")
    def create_cmd(name, description, no_edit):
        """Create a new browser command."""
        cmds_dir = get_browser_cmds_dir()
        cmd_dir = cmds_dir / name

        if cmd_dir.exists():
            click.echo(f"Error: Command '{name}' already exists.", err=True)
            sys.exit(1)

        cmd_dir.mkdir(parents=True)
        cmd_file = cmd_dir / "COMMAND.md"
        content = _COMMAND_TEMPLATE.format(name=name)

        # Inject description into frontmatter if provided
        if description:
            content = content.replace("description:", f"description: {description}", 1)

        cmd_file.write_text(content, encoding="utf-8")
        click.echo(f"Created: {cmd_file}")

        if not no_edit:
            open_editor(cmd_file)

    @cmd_group.command("edit")
    @click.argument("name", type=_CmdNameType())
    def edit_cmd(name):
        """Edit a browser command in the default editor."""
        cmds_dir = get_browser_cmds_dir()
        cmd_dir = cmds_dir / name

        if not cmd_dir.exists():
            click.echo(f"Error: Command '{name}' not found.", err=True)
            sys.exit(1)

        cmd_file = cmd_dir / "COMMAND.md"
        if not cmd_file.exists():
            click.echo(f"Error: COMMAND.md missing in '{name}'.", err=True)
            sys.exit(1)

        open_editor(cmd_file)

    @cmd_group.command("show")
    @click.argument("name", type=_CmdNameType())
    def show_cmd(name):
        """Show the content of a browser command."""
        cmds_dir = get_browser_cmds_dir()
        cmd_dir = cmds_dir / name
        cmd = BrowserCmd.from_path(cmd_dir)

        if cmd is None:
            click.echo(f"Error: Command '{name}' not found.", err=True)
            sys.exit(1)

        cmd_file = cmd_dir / "COMMAND.md"
        click.echo(cmd_file.read_text(encoding="utf-8"))

    @cmd_group.command("rename")
    @click.argument("old_name", type=_CmdNameType())
    @click.argument("new_name")
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation if overwriting.")
    def rename_cmd(old_name, new_name, force):
        """Rename a browser command."""
        cmds_dir = get_browser_cmds_dir()
        old_path = cmds_dir / old_name

        if not old_path.exists():
            click.echo(f"Error: Command '{old_name}' not found.", err=True)
            sys.exit(1)

        new_path = cmds_dir / new_name
        if new_path.exists():
            if not force:
                click.confirm(f"Command '{new_name}' already exists. Overwrite?", abort=True)
            shutil.rmtree(new_path)

        shutil.move(str(old_path), str(new_path))

        # Update the name field in COMMAND.md frontmatter
        cmd_file = new_path / "COMMAND.md"
        if cmd_file.exists():
            content = cmd_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        frontmatter = yaml.safe_load(parts[1]) or {}
                        frontmatter["name"] = new_name
                        new_fm = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
                        cmd_file.write_text(f"---\n{new_fm}---{parts[2]}", encoding="utf-8")
                    except Exception as exc:
                        click.echo(f"Warning: Could not update COMMAND.md frontmatter: {exc}", err=True)

        click.echo(f"Renamed: {old_name} -> {new_name}")

    @cmd_group.command("delete")
    @click.argument("name", type=_CmdNameType())
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation.")
    def delete_cmd(name, force):
        """Delete a browser command."""
        cmds_dir = get_browser_cmds_dir()
        cmd_path = cmds_dir / name

        if not cmd_path.exists():
            click.echo(f"Error: Command '{name}' not found.", err=True)
            sys.exit(1)

        if not force:
            click.confirm(f"Delete browser command '{name}'?", abort=True)

        shutil.rmtree(cmd_path)
        click.echo(f"Deleted: {name}")

    return CommandManifest(name="cmd", click_command=cmd_group)
