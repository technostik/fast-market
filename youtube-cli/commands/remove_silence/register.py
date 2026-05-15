from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import click

from commands.base import CommandManifest


def remove_silence(
    input_path: str,
    output_path: str,
    threshold_db: float = -35,
    min_duration: float = 0.5,
) -> None:
    """Remove silence segments from a video using ffmpeg silencedetect + concat."""
    result = subprocess.run(
        [
            "ffmpeg", "-i", input_path,
            "-af", f"silencedetect=noise={threshold_db}dB:duration={min_duration}",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    stderr = result.stderr

    starts = [float(m) for m in re.findall(r"silence_start: ([\d.e+-]+)", stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.e+-]+)", stderr)]

    dur_match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", stderr)
    if not dur_match:
        raise RuntimeError("Could not determine video duration from ffmpeg output")
    h, m, s = dur_match.groups()
    total_duration = int(h) * 3600 + int(m) * 60 + float(s)

    segments: list[tuple[float, float]] = []
    current = 0.0
    for start, end in zip(starts, ends):
        if start > current + 0.01:
            segments.append((current, start))
        current = end
    if current < total_duration - 0.01:
        segments.append((current, total_duration))

    if not segments:
        raise RuntimeError("No non-silent segments detected — check threshold")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        concat_file = f.name
        abs_input = os.path.abspath(input_path)
        for seg_start, seg_end in segments:
            f.write(f"file '{abs_input}'\n")
            f.write(f"inpoint {seg_start:.6f}\n")
            f.write(f"outpoint {seg_end:.6f}\n")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_file,
                "-c:v", "libx264", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k",
                output_path,
            ],
            check=True,
        )
    finally:
        os.unlink(concat_file)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("remove-silence")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
    @click.option("--threshold", "-t", default=-35.0, show_default=True, help="Silence threshold in dB")
    @click.option("--min-duration", "-d", default=0.5, show_default=True, help="Min silence duration to remove (seconds)")
    def remove_silence_cmd(
        input_file: str,
        output: str | None,
        threshold: float,
        min_duration: float,
    ):
        """Remove silence from a video file using ffmpeg."""
        input_path = Path(input_file).resolve()
        if output:
            output_path = Path(output).resolve()
        else:
            output_path = input_path.parent / f"{input_path.stem}_nosilence{input_path.suffix}"

        click.echo(f"Removing silence from {input_path.name}...", err=True)
        remove_silence(str(input_path), str(output_path), threshold, min_duration)
        click.echo(str(output_path))

    return CommandManifest(name="remove-silence", click_command=remove_silence_cmd)
