from __future__ import annotations

import subprocess
from pathlib import Path

import click

from commands.base import CommandManifest


def get_duration(file_path: str) -> float:
    """Return the duration of a video file in seconds (ffprobe)."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(Path(file_path).resolve()),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError(
            f"ffprobe failed for {file_path} (exit {result.returncode}):\n"
            f"{result.stderr.strip()}"
        )


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("duration")
    @click.argument("input_file", type=click.Path(exists=True))
    def duration_cmd(input_file: str):
        """Print the duration of a video file in seconds."""
        try:
            click.echo(f"{get_duration(input_file):.3f}")
        except RuntimeError as exc:
            raise click.ClickException(str(exc))

    return CommandManifest(name="duration", click_command=duration_cmd)
