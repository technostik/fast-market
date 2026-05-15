from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click

from commands.base import CommandManifest


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    font_size: int = 24,
) -> None:
    """Burn SRT subtitles into a video using ffmpeg."""
    abs_srt = os.path.abspath(srt_path)
    # Escape colons and backslashes for the ffmpeg filter string
    escaped = abs_srt.replace("\\", "/").replace(":", "\\:")

    force_style = (
        f"FontSize={font_size},Bold=1,Outline=2,Shadow=1,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,MarginV=50"
    )

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"subtitles='{escaped}':force_style='{force_style}'",
            "-c:v", "libx264", "-preset", "medium",
            "-c:a", "copy",
            output_path,
        ],
        check=True,
    )


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("burn-subtitles")
    @click.argument("video_file", type=click.Path(exists=True))
    @click.argument("srt_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
    @click.option("--font-size", default=24, show_default=True, help="Subtitle font size")
    def burn_subtitles_cmd(
        video_file: str,
        srt_file: str,
        output: str | None,
        font_size: int,
    ):
        """Burn SRT subtitles into a video file."""
        video_path = Path(video_file).resolve()
        if output:
            output_path = Path(output).resolve()
        else:
            output_path = video_path.parent / f"{video_path.stem}_subtitled{video_path.suffix}"

        click.echo(f"Burning subtitles into {video_path.name}...", err=True)
        burn_subtitles(str(video_path), srt_file, str(output_path), font_size)
        click.echo(str(output_path))

    return CommandManifest(name="burn-subtitles", click_command=burn_subtitles_cmd)
