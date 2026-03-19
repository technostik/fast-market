from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("alias")
    @click.argument("name", required=False)
    @click.argument("command", required=False)
    @click.option("--list", "-l", "list_aliases", is_flag=True, help="List all aliases")
    @click.option("--remove", "-r", is_flag=True, help="Remove the specified alias")
    @click.option(
        "--config-path", is_flag=True, help="Show path to aliases config file"
    )
    @click.option(
        "--config-file", is_flag=True, help="Show path to aliases config file"
    )
    @click.option(
        "--file", "-f", type=click.Path(exists=True), help="Load aliases from YAML file"
    )
    @click.option("--export", "-e", is_flag=True, help="Export all aliases to stdout")
    @click.option(
        "--format",
        "-o",
        "fmt",
        type=click.Choice(["text", "json", "yaml"]),
        default="text",
        help="Output format",
    )
    @click.option(
        "--description", "-d", "description", help="Description for the alias"
    )
    def alias_cmd(
        name,
        command,
        list_aliases,
        remove,
        config_path,
        config_file,
        file,
        export,
        fmt,
        description,
    ):
        """Manage command aliases for prompt task.

        Examples:
          prompt alias                           # List all aliases
          prompt alias --list                    # List all aliases
          prompt alias alert-me "message alert"  # Create/update alias
          prompt alias alert-me "message alert" -d "Alert me with a message"  # Create with description
          prompt alias alert-me --remove         # Remove alias
          prompt alias --config-path             # Show config file path
          prompt alias --export > backup.yaml     # Export aliases
          prompt alias --file team.yaml          # Import aliases from file
        """
        from common.core.aliases import (
            create_or_update_alias,
            export_aliases,
            get_all_aliases,
            get_alias_config_path,
            load_aliases,
            merge_aliases_from_file,
            remove_alias,
        )

        if config_path or config_file:
            config_path_val = get_alias_config_path()
            click.echo(config_path_val)
            return

        if file:
            file_path = Path(file)
            try:
                count = merge_aliases_from_file(file_path)
                click.echo(f"✓ Loaded {count} aliases from {file_path}")
            except (FileNotFoundError, ValueError) as exc:
                click.echo(f"Error: {exc}", err=True)
                sys.exit(1)
            return

        if export:
            if fmt == "json":
                aliases = get_all_aliases()
                click.echo(json.dumps({"aliases": aliases}, indent=2))
            elif fmt == "yaml":
                click.echo(export_aliases())
            else:
                click.echo(export_aliases())
            return

        if list_aliases or (not name and not command):
            _list_all_aliases(fmt)
            return

        if not name:
            click.echo("Error: Alias name required", err=True)
            sys.exit(1)

        if remove:
            if remove_alias(name):
                click.echo(f"✓ Alias removed: {name}")
            else:
                click.echo(f"Error: Alias not found: {name}", err=True)
                sys.exit(1)
            return

        if not command:
            _show_alias(name, fmt)
            return

        is_new = create_or_update_alias(name, command, description)
        if is_new:
            click.echo(f"✓ Alias created: {name} → {command}")
        else:
            click.echo(f"✓ Alias updated: {name} → {command}")

    return CommandManifest(name="alias", click_command=alias_cmd)


def _list_all_aliases(fmt: str) -> None:
    """List all aliases in the specified format."""
    from common.core.aliases import get_all_aliases

    aliases = get_all_aliases()

    if fmt == "json":
        click.echo(json.dumps({"aliases": aliases}, indent=2))
        return

    if fmt == "yaml":
        data = {"aliases": aliases}
        click.echo(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return

    if not aliases:
        click.echo(
            "No aliases defined. Use 'prompt alias <name> <command>' to create one."
        )
        return

    for alias_name, alias_data in sorted(aliases.items()):
        if isinstance(alias_data, dict):
            cmd = alias_data.get("command", "")
            desc = alias_data.get("description", "")
        else:
            cmd = alias_data
            desc = ""
        if desc:
            click.echo(f"{alias_name}: {cmd} - {desc}")
        else:
            click.echo(f"{alias_name}: {cmd}")


def _show_alias(name: str, fmt: str) -> None:
    """Show a specific alias."""
    from common.core.aliases import get_all_aliases

    aliases = get_all_aliases()

    if name not in aliases:
        click.echo(f"Error: Alias not found: {name}", err=True)
        sys.exit(1)

    alias_data = aliases[name]
    if isinstance(alias_data, dict):
        actual_cmd = alias_data.get("command", "")
        desc = alias_data.get("description", "")
    else:
        actual_cmd = alias_data
        desc = ""

    if fmt == "json":
        click.echo(
            json.dumps(
                {"alias": name, "command": actual_cmd, "description": desc}, indent=2
            )
        )
    elif fmt == "yaml":
        data = {"aliases": {name: {"command": actual_cmd, "description": desc}}}
        click.echo(yaml.dump(data, default_flow_style=False, sort_keys=False))
    else:
        if desc:
            click.echo(f"{name}: {actual_cmd}")
            click.echo(f"  Description: {desc}")
        else:
            click.echo(f"{name}: {actual_cmd}")
