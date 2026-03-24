from __future__ import annotations

import subprocess
from pathlib import Path

import click

from commands.base import CommandManifest
from core.config import load_config


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("upload-yt-short")
    @click.option("--title", "-t", required=True, help="Title for the TikTok video")
    @click.option("--url", "-u", required=True, help="YouTube Short URL")
    @click.pass_context
    def upload_yt_short_cmd(ctx, title, url, **kwargs):
        """Upload a YouTube Short to TikTok."""
        config = load_config()

        tiktok_config = config.get("tiktok", {})
        uploader_path = tiktok_config.get("tiktok_auto_uploader_path")
        username = tiktok_config.get("username")

        if not uploader_path:
            raise click.ClickException(
                "TikTokAutoUploader path not configured. "
                "Add 'tiktok.tiktok_auto_uploader_path' to config.yaml"
            )
        if not username:
            raise click.ClickException(
                "TikTok username not configured. Add 'tiktok.username' to config.yaml"
            )

        uploader_path = Path(uploader_path).expanduser()
        cli_path = uploader_path / "cli.py"

        if not cli_path.exists():
            raise click.ClickException(f"cli.py not found at {cli_path}")

        python_path = uploader_path / "venv" / "bin" / "python"
        if not python_path.exists():
            python_path = "python"

        cmd = [
            str(python_path),
            str(cli_path),
            "upload",
            "-u",
            username,
            "-t",
            f'"{title}"',
            "-yt",
            url,
        ]

        click.echo(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=str(uploader_path),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            click.echo(f"Error: {result.stderr}", err=True)
            raise click.ClickException("Upload failed")

        click.echo(result.stdout)
        click.echo("Upload successful!")

    return CommandManifest(
        name="upload-yt-short",
        click_command=upload_yt_short_cmd,
    )
