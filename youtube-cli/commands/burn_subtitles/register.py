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
    progress_cb=None,
) -> None:
    """Burn ASS karaoke subtitles into a video using ffmpeg subtitles filter.
    If progress_cb is provided it receives (current_pct, total_pct).
    """
    abs_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
    force_style = (
        f"Alignment=10,Fontsize={subtitle_size},"
        "MarginL=0,MarginR=0,MarginV=0,"
        "Outline=8,Shadow=14,BackColour=&H80000000&"
    )
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles='{abs_ass}':force_style='{force_style}'",
        "-vcodec", "h264",
        "-acodec", "aac",
        "-progress", "pipe:1",
        "-nostats",
        output_path,
    ]
    if progress_cb is None:
        subprocess.run(cmd, check=True)
        return

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    total_duration = None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=", 1)[1])
                cur_sec = ms / 1_000_000
                if total_duration is None:
                    # try to get duration via ffprobe once
                    import json
                    dur_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path]
                    dur_out = subprocess.check_output(dur_cmd, text=True)
                    total_duration = float(json.loads(dur_out)["format"]["duration"])
                if total_duration and total_duration > 0:
                    pct = min(100.0, cur_sec / total_duration * 100)
                    progress_cb(round(pct, 1), 100)
            except Exception:
                pass
    rc = proc.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


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
        burn_ass_subtitles(str(video_path), ass_file, str(output_path), font_size, progress_cb=None)
        click.echo(str(output_path))

    return CommandManifest(name="burn-subtitles", click_command=burn_subtitles_cmd)
