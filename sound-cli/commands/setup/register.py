from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import get_editor
from common.core.paths import get_tool_config
from common.core.yaml_utils import dump_yaml
from core.config import get_default_config


def register(plugin_manifests: dict) -> CommandManifest:

    @click.group("setup", invoke_without_command=True)
    @click.option("--show-config", "-c", is_flag=True, help="Show current configuration")
    @click.option("--config-path", "-p", is_flag=True, help="Show config file path")
    @click.pass_context
    def setup_cmd(ctx, show_config, config_path):
        """Manage sound-agent configuration."""

        if ctx.invoked_subcommand is not None:
            return

        if show_config:
            config_file = get_tool_config("sound")
            if config_file.exists():
                data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
                click.echo(dump_yaml(data, sort_keys=False))
            else:
                click.echo("(no configuration file found)")
                click.echo(f"Default config path: {config_file}")
            return

        if config_path:
            click.echo(str(get_tool_config("sound")))
            return

        click.echo(ctx.get_help())

    @setup_cmd.command("path")
    @click.argument("path", required=False, default=None)
    def path_cmd(path):
        """Show or set the output path (common workdir).

        With no argument, prints the current config file path.
        With a PATH argument, sets the common workdir to that path.
        """
        if path:
            from common.core.config import load_common_config, save_common_config

            config = load_common_config()
            config["workdir"] = str(Path(path).expanduser().resolve())
            save_common_config(config)
            click.echo(f"Workdir set to: {config['workdir']}")
        else:
            config_file = get_tool_config("sound")
            click.echo(f"Tool config: {config_file}")
            from common.core.config import load_common_config

            common = load_common_config()
            workdir = common.get("workdir", "(not set)")
            click.echo(f"Workdir:    {workdir}")

    @setup_cmd.command("edit")
    def edit_cmd():
        """Edit the configuration file in the default editor."""
        config_path = get_tool_config("sound")
        config_path.parent.mkdir(parents=True, exist_ok=True)

        if not config_path.exists():
            config_path.write_text(
                dump_yaml(get_default_config(), sort_keys=False),
                encoding="utf-8",
            )

        editor = get_editor()
        try:
            subprocess.run([editor, str(config_path)], check=True)
        except subprocess.CalledProcessError:
            click.echo("Editor closed with non-zero exit code.", err=True)
            sys.exit(1)

    @setup_cmd.command("reset")
    def reset_cmd():
        """Reset configuration to defaults, keeping a backup."""
        config_path = get_tool_config("sound")

        if config_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_path = config_path.with_name(
                f"config.yaml.{timestamp}.bak"
            )
            shutil.copy2(config_path, backup_path)
            click.echo(f"Backed up existing config to: {backup_path}")

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            dump_yaml(get_default_config(), sort_keys=False),
            encoding="utf-8",
        )
        click.echo(f"Default configuration written to: {config_path}")
        click.echo("Configuration has been reset to defaults.")

    return CommandManifest(name="setup", click_command=setup_cmd)
