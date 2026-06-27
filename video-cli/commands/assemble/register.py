from __future__ import annotations

import json
from pathlib import Path

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("assemble")
    @click.argument("image_file", type=click.Path(exists=True))
    @click.argument("audio_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None,
                  help="Output MP4 path (default: <audio_stem>_clip.mp4 next to audio file)")
    @click.option("--zoom-from", type=float, default=1.0, show_default=True,
                  help="Ken Burns start zoom level")
    @click.option("--zoom-to", type=float, default=1.3, show_default=True,
                  help="Ken Burns end zoom level")
    @click.option("--fps", type=int, default=24, show_default=True,
                  help="Output frame rate")
    @click.option("--format", "-F", "fmt", type=click.Choice(["text", "json"]), default="text",
                  show_default=True, help="Output format")
    def assemble_cmd(image_file: str, audio_file: str, output: str | None,
                     zoom_from: float, zoom_to: float, fps: int, fmt: str):
        """Assemble a still image and audio into an animated Ken Burns MP4 clip.

        The clip duration matches the audio file length. The image is zoomed
        slowly from ZOOM_FROM to ZOOM_TO (Ken Burns effect). Output is 1280×720.
        """
        from commands.assemble.assembler import ken_burns_clip
        from moviepy import AudioFileClip

        audio_path = Path(audio_file).resolve()
        if output is None:
            output_path = audio_path.parent / f"{audio_path.stem}_clip.mp4"
        else:
            output_path = Path(output).resolve()

        click.echo(f"Assembling {Path(image_file).name} + {audio_path.name} …", err=True)
        result_path = ken_burns_clip(
            image_path=str(Path(image_file).resolve()),
            audio_path=str(audio_path),
            output_path=str(output_path),
            zoom_from=zoom_from,
            zoom_to=zoom_to,
            fps=fps,
        )

        audio = AudioFileClip(str(audio_path))
        duration = audio.duration
        audio.close()

        if fmt == "json":
            import subprocess
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height",
                     "-of", "json", result_path],
                    capture_output=True, text=True,
                )
                streams = json.loads(probe.stdout).get("streams", [{}])
                w = streams[0].get("width", 1280)
                h = streams[0].get("height", 720)
            except Exception:
                w, h = 1280, 720
            click.echo(json.dumps({
                "path": result_path,
                "duration_secs": round(duration, 3),
                "width": w,
                "height": h,
            }))
        else:
            click.echo(result_path)

    return CommandManifest(name="assemble", click_command=assemble_cmd)
