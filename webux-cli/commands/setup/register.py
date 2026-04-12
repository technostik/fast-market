from __future__ import annotations

import shutil

import click
import yaml

from commands.base import CommandManifest
from common.core.paths import get_tool_config_path


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup")
    def setup_group() -> None:
        """Manage webux setup and configuration."""
        pass

    @setup_group.command("show")
    def show_cmd() -> None:
        """Show current config as YAML."""
        config_path = get_tool_config_path("webux")
        if config_path.exists():
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {}
        click.echo(yaml.dump(config, default_flow_style=False, sort_keys=False).strip())

    @setup_group.command("reset")
    def reset_cmd() -> None:
        """Back up existing config and write a fresh empty config."""
        config_path = get_tool_config_path("webux")
        if config_path.exists():
            backup_path = config_path.with_suffix(".yaml.bak")
            shutil.copy2(config_path, backup_path)
            click.echo(f"Backed up existing config to {backup_path}")
        config_path.write_text("{}\n")
        click.echo(f"Reset config to empty dict at {config_path}")

    @setup_group.command("show-path")
    def show_path_cmd() -> None:
        """Print the config file path."""
        click.echo(str(get_tool_config_path("webux")))

    return CommandManifest(name="setup", click_command=setup_group)
