from __future__ import annotations

import click

from commands.base import CommandManifest
from common.core.paths import get_tool_config


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("setup")
    @click.option("--show", "-s", is_flag=True, help="Display current configuration")
    @click.option("--locate", "-l", is_flag=True, help="Show config file path")
    @click.option("--create", "-c", is_flag=True, help="Create default config file")
    def setup_cmd(show, locate, create, **kwargs):
        """Setup and show tiktok-agent configuration."""
        from pathlib import Path

        cfg_path = get_tool_config("tiktok")
        default_config = """# TikTok agent configuration
tiktok:
  # Path to TikTokAutoUploader installation
  # tiktok_auto_uploader_path: "/path/to/TikTokAutoUploader"

  # TikTok username for uploads
  # username: "your_username"
"""

        if locate:
            click.echo(f"Config file: {cfg_path}")
            if cfg_path.exists():
                click.echo(f"Status: exists")
            else:
                click.echo(f"Status: does not exist (use --create to create)")

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
                click.echo("\nEdit the file to add your TikTok settings:")
                click.echo(f"  nano {cfg_path}")

        else:
            click.echo("Usage: tiktok setup [OPTIONS]")
            click.echo("")
            click.echo("Options:")
            click.echo("  --locate    Show config file locations")
            click.echo("  --show      Display current configuration")
            click.echo("  --create    Create default configuration file")
            click.echo("")
            click.echo("First time setup:")
            click.echo("  1. tiktok setup --create")
            click.echo("  2. Edit config to add tiktok_auto_uploader_path and username")
            click.echo("  3. Run 'tiktok upload-yt-short -t title -u url' to upload")

    return CommandManifest(
        name="setup",
        click_command=setup_cmd,
    )
