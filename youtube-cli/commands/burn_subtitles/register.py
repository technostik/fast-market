from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click

from commands.base import CommandManifest


def burn_ass_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
    subtitle_size: int = 96,
) -> None:
    """Burn ASS karaoke subtitles into a video using ffmpeg subtitles filter."""
    abs_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
    force_style = (
        f"Alignment=10,Fontsize={subtitle_size},"
        "MarginL=0,MarginR=0,MarginV=0,"
        "Outline=8,Shadow=14,BackColour=&H80000000&"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"subtitles='{abs_ass}':force_style='{force_style}'",
            "-vcodec", "h264",
            "-acodec", "aac",
            output_path,
        ],
        check=True,
    )


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("burn-subtitles")
    @click.argument("video_file", type=click.Path(exists=True))
    @click.argument("ass_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
    @click.option("--font-size", default=96, show_default=True, help="Subtitle font size")
    def burn_subtitles_cmd(
        video_file: str,
        ass_file: str,
        output: str | None,
        font_size: int,
    ):
        """Burn ASS karaoke subtitles (green/white, middle-centered) into a video."""
        video_path = Path(video_file).resolve()
        output_path = (
            Path(output).resolve() if output
            else video_path.parent / f"{video_path.stem}_subtitled{video_path.suffix}"
        )
        click.echo(f"Burning subtitles into {video_path.name}...", err=True)
        burn_ass_subtitles(str(video_path), ass_file, str(output_path), font_size)
        click.echo(str(output_path))

    return CommandManifest(name="burn-subtitles", click_command=burn_subtitles_cmd)
