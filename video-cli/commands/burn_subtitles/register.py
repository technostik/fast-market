from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import click

from commands.base import CommandManifest

# ASS style alignment values. 2/5/8 are the numpad bottom/middle/top-center
# anchors; 10 is the value the ASS writer puts in the style line and renders
# top-left here. "middle" (5) reproduces the pre-`--position` output exactly
# (see the alignment note in _apply_position).
POSITIONS = {"top-left": 10, "top": 8, "middle": 5, "bottom": 2}

DEFAULT_POSITION = "middle"


def _force_style(subtitle_size: int) -> str:
    """Build the ffmpeg ASS ``force_style`` string.

    Alignment is deliberately absent: the ``Alignment`` field of ``force_style``
    is not interchangeable with the ASS style field on this ffmpeg/libass build
    (``force_style`` 10 renders middle-center, 5 renders top-left), so placement
    is applied to the style line of a rewritten ASS copy instead.
    """
    return (
        f"Fontsize={subtitle_size},"
        "MarginL=0,MarginR=0,MarginV=0,"
        "Outline=8,Shadow=14,BackColour=&H80000000&"
    )


def _apply_position(ass_content: str, position: str) -> str:
    """Force the subtitle style to ``position``.

    Rewrites the ``Alignment`` field of every style line. An inline ``{\anN}``
    override is not used: this ffmpeg/libass build mirrors it, while the style
    field renders correctly. The style field value 10 (what the ASS writer
    emits) renders top-left here, so ``middle`` (5) is what matches the old
    middle-centered output.
    """
    try:
        alignment = POSITIONS[position]
    except KeyError:
        raise ValueError(
            f"Unknown subtitle position {position!r}; expected one of {tuple(POSITIONS)}"
        ) from None

    alignment_index = None
    rewritten = []
    for line in ass_content.splitlines():
        if line.startswith("Format:") and "Alignment" in line and alignment_index is None:
            alignment_index = [part.strip() for part in line.split(",")][1:].index("Alignment")
        if line.startswith("Style:") and alignment_index is not None:
            fields = line.split(",")
            # fields[0] is "Style: Default"; the format columns start at 1.
            fields[alignment_index + 1] = str(alignment)
            line = ",".join(fields)
        rewritten.append(line)
    if alignment_index is None:
        raise ValueError(
            "ASS file has no style Format line with an Alignment column; "
            "cannot apply a subtitle position"
        )
    return "\n".join(rewritten)


def burn_ass_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
    subtitle_size: int = 96,
    progress_cb=None,
    position: str = DEFAULT_POSITION,
) -> None:
    """Burn ASS karaoke subtitles into a video using ffmpeg subtitles filter.
    If progress_cb is provided it receives (current_pct, total_pct).
    ``position`` is one of ``POSITIONS``; the default matches the historical
    middle-centered placement.
    """
    # Rewritten copy: force_style cannot be trusted for Alignment (see above).
    positioned = tempfile.NamedTemporaryFile(
        "w", suffix=".ass", dir=os.path.dirname(os.path.abspath(ass_path)),
        encoding="utf-8", delete=False,
    )
    try:
        positioned.write(_apply_position(Path(ass_path).read_text(encoding="utf-8"), position))
        positioned.close()
        abs_ass = positioned.name.replace("\\", "/").replace(":", "\\:")
        force_style = _force_style(subtitle_size)
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
        _burn_with_progress(cmd, video_path, progress_cb)
    finally:
        positioned.close()
        os.unlink(positioned.name)


def _burn_with_progress(cmd: list[str], video_path: str, progress_cb) -> None:
    import json

    total_duration = None
    try:
        dur_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path]
        dur_out = subprocess.check_output(dur_cmd, text=True)
        total_duration = float(json.loads(dur_out)["format"]["duration"])
    except Exception:
        pass

    last_pct = [0.0]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms=") and total_duration:
            try:
                us = int(line.split("=", 1)[1])
                cur_sec = us / 1_000_000
                pct = min(100.0, cur_sec / total_duration * 100)
                if abs(pct - last_pct[0]) >= 1:
                    last_pct[0] = pct
                    progress_cb(pct, 100)
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
    @click.option(
        "--position",
        type=click.Choice(list(POSITIONS)),
        default=DEFAULT_POSITION,
        show_default=True,
        help="Subtitle placement (middle preserves the historical middle-centered rendering)",
    )
    @click.option("--modal/--local", default=False, show_default=True, help="Run this step on Modal instead of locally.")
    def burn_subtitles_cmd(
        video_file: str,
        ass_file: str,
        output: str | None,
        font_size: int,
        position: str,
        modal: bool,
    ):
        """Burn ASS karaoke subtitles (green/white) into a video."""
        video_path = Path(video_file).resolve()
        output_path = (
            Path(output).resolve() if output
            else video_path.parent / f"{video_path.stem}_subtitled{video_path.suffix}"
        )
        click.echo(f"Burning subtitles into {video_path.name} ({position})...", err=True)
        if modal:
            from commands.remote import run_remote_burn_subtitles
            run_remote_burn_subtitles(
                video_path, Path(ass_file).resolve(), output_path, font_size, position
            )
        else:
            burn_ass_subtitles(
                str(video_path), ass_file, str(output_path), font_size,
                progress_cb=None, position=position,
            )
        click.echo(str(output_path))

    return CommandManifest(name="burn-subtitles", click_command=burn_subtitles_cmd)
