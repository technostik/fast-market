from __future__ import annotations

import os
from pathlib import Path

import click

from commands.base import CommandManifest


def concat_videos_simple(input_files: list[str], output_file: str) -> str:
    """Concatenate 2+ videos into one (hard cut, no transition).

    Always re-encodes to libx264/aac so mismatched source codecs or
    resolutions are handled by construction, matching this repo's
    convention (no separate codec-compatibility pre-check).
    """
    from moviepy import VideoFileClip, concatenate_videoclips

    clips = [VideoFileClip(f) for f in input_files]
    same_size = len({tuple(c.size) for c in clips}) == 1
    method = "chain" if same_size else "compose"
    final = concatenate_videoclips(clips, method=method)

    temp_audio = os.path.join(os.path.dirname(os.path.abspath(output_file)), "temp-audio-concat.m4a")
    final.write_videofile(
        output_file,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=temp_audio,
        remove_temp=True,
        audio_bitrate="192k",
        preset="medium",
    )

    final.close()
    for c in clips:
        c.close()

    return output_file


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("concat")
    @click.argument("input_files", nargs=-1, type=click.Path(exists=True), required=True)
    @click.option("--output", "-o", type=click.Path(), required=True, help="Output file path")
    @click.option("--modal/--local", default=False, show_default=True, help="Run this step on Modal instead of locally.")
    def concat_cmd(input_files: tuple[str, ...], output: str, modal: bool):
        """Concatenate 2+ videos into one (hard cut, no transition)."""
        if len(input_files) < 2:
            raise click.UsageError("concat requires at least 2 input videos")
        output_path = Path(output).resolve()
        input_paths = [Path(f).resolve() for f in input_files]

        click.echo(f"Concatenating {len(input_paths)} videos...", err=True)
        if modal:
            from commands.remote import run_remote_concat_videos
            run_remote_concat_videos(input_paths, output_path)
        else:
            concat_videos_simple([str(p) for p in input_paths], str(output_path))
        click.echo(str(output_path))

    return CommandManifest(name="concat", click_command=concat_cmd)
