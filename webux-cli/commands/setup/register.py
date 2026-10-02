from __future__ import annotations

import shutil

import click
import yaml

from commands.base import CommandManifest
from common.core.config import load_tool_config, save_tool_config
from common.core.paths import get_tool_config_path
from common.webux.theme import DEFAULT_THEME, THEME_NAMES, resolve_theme


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

    @setup_group.group("theme")
    def theme_group() -> None:
        """Manage the default webux theme (dark|light|blue)."""
        pass

    @theme_group.command("show")
    def theme_show_cmd() -> None:
        """Print the configured default theme and available themes."""
        config = load_tool_config("webux")
        click.echo(f"theme: {resolve_theme(config)}")
        click.echo(f"available: {', '.join(THEME_NAMES)}")
        click.echo(f"config_path: {get_tool_config_path('webux')}")

    @theme_group.command("set")
    @click.argument("name", type=click.Choice(list(THEME_NAMES)))
    def theme_set_cmd(name: str) -> None:
        """Persist the default theme (used on first paint; browser can override)."""
        config = load_tool_config("webux")
        config["theme"] = name
        save_tool_config("webux", config)
        click.echo(f"theme set to {name} (default was {DEFAULT_THEME})")

    return CommandManifest(name="setup", click_command=setup_group)
