from __future__ import annotations

import shutil

import click

from commands.base import CommandManifest
from common.core.paths import get_tool_config, get_tool_config_path


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("setup")
    @click.option("--show", "-s", is_flag=True, help="Display current configuration")
    @click.option("--locate", "-l", is_flag=True, help="Show config file path")
    @click.option("--create", "-c", is_flag=True, help="Create default config file")
    @click.option("--reset", "-R", is_flag=True, help="Reset config to defaults (backs up existing)")
    def setup_cmd(show, locate, create, reset, **kwargs):
        """Setup and show youtube-agent configuration."""
        from pathlib import Path

        cfg_path = get_tool_config("youtube")
        default_config = """# YouTube agent configuration
youtube:
  # Get your channel ID from YouTube Studio > Settings > Channel
  # Or use any channel ID you want to interact with
  channel_id: ""

  # Quota limit (default: 10000 units/day)
  quota_limit: 10000

  # Optional: explicit path to client_secret.json
  # If not specified, looks for client_secret.json in config directory
  # client_secret_path: "~/.config/fast-market/config/client_secret.json"
"""

        if locate:
            click.echo(f"Config file: {cfg_path}")
            if cfg_path.exists():
                click.echo(f"Status: exists")
            else:
                click.echo(f"Status: does not exist (use --create to create)")

            secret_path = cfg_path.parent / "client_secret.json"
            click.echo(f"Client secret: {secret_path}")
            if secret_path.exists():
                click.echo(f"Client secret: exists")
            else:
                click.echo(f"Client secret: does not exist")

            token_path = cfg_path.parent / "token.json"
            click.echo(f"OAuth token: {token_path}")
            if token_path.exists():
                click.echo(f"OAuth token: exists (authenticated)")
            else:
                click.echo(
                    f"OAuth token: does not exist (run a command to authenticate)"
                )

        elif show:
            if cfg_path.exists():
                click.echo(f"# Current configuration ({cfg_path}):")
                click.echo(cfg_path.read_text())
            else:
                click.echo("No configuration file found. Use --create to create one.")
                click.echo(f"Default configuration would be:\n{default_config}")

        elif create:
            if cfg_path.exists():
                click.echo(f"Config already exists at {cfg_path}")
                click.echo("Use --show to view current config or --locate to find it")
            else:
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(default_config)
                click.echo(f"Created default config at {cfg_path}")
                click.echo("\nEdit the file to add your channel_id:")
                click.echo(f"  nano {cfg_path}")

        elif reset:
            cfg_path = get_tool_config_path("youtube")
            if cfg_path.exists():
                backup_path = cfg_path.with_name("config.yaml.bak")
                shutil.copy2(str(cfg_path), str(backup_path))
                click.echo(f"Backed up existing config to {backup_path}")
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(default_config)
            click.echo(f"Reset configuration to defaults at {cfg_path}")

        else:
            click.echo("Usage: youtube setup [OPTIONS]")
            click.echo("")
            click.echo("Options:")
            click.echo("  --locate    Show config file locations")
            click.echo("  --show      Display current configuration")
            click.echo("  --create    Create default configuration file")
            click.echo("")
            click.echo("First time setup:")
            click.echo("  1. youtube setup --create")
            click.echo("  2. Edit config to add your channel_id")
            click.echo("  3. Ensure client_secret.json exists in config directory")
            click.echo("  4. Run 'youtube search test' to authenticate")

    return CommandManifest(
        name="setup",
        click_command=setup_cmd,
    )
