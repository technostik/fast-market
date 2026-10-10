from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest


def get_duration(file_path: str) -> float:
    """Return the duration of a video file in seconds.

    Uses the container header. Chrome WebM often stores ``Duration: N/A``;
    fall back to the packet timestamps in that case.
    """
    from commands.media_open import container_duration_seconds, packet_span_seconds

    resolved = str(Path(file_path).resolve())
    known = container_duration_seconds(resolved)
    if known is not None:
        return known
    spanned = packet_span_seconds(resolved)
    if spanned is None:
        raise RuntimeError(
            f"Could not read a duration for {file_path}. "
            "ffprobe reported no container duration and no packet timestamps."
        )
    return spanned


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
