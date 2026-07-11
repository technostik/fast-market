from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest
from common.cli.helpers import out

from .analysis import segment_words, transcribe, write_segments


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("segment")
    @click.argument("voice_file")
    @click.option(
        "--output-dir", "-o", default=None,
        help="Output directory (default: <voice_parent>/<stem>_segments).",
    )
    @click.option(
        "--engine", type=click.Choice(["whisperx", "groq"]), default="whisperx",
        help="Transcription engine. whisperx = local word-aligned model; groq = hosted whisper-large-v3.",
    )
    @click.option("--model", default="medium", help="whisperx model size (tiny..large).")
    @click.option("--language", default="auto", help="Language code or 'auto'.")
    @click.option("--min-segment", default=10.0, type=float,
                  help="Target minimum scene duration in seconds (merge shorter scenes).")
    @click.option("--max-segment", default=30.0, type=float,
                  help="Hard maximum scene duration in seconds (split longer scenes).")
    @click.option("--silence", default=0.6, type=float,
                  help="Minimum pause (seconds) that strongly prefers a cut at that boundary.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="json")
    def segment_cmd(
        voice_file, output_dir, engine, model, language,
        min_segment, max_segment, silence, fmt,
    ):
        src = Path(voice_file).expanduser()
        if not src.exists():
            raise click.ClickException(f"Voice file not found: {src}")

        if output_dir is None:
            output_dir = src.parent / f"{src.stem}_segments"
        output_dir = Path(output_dir)

        manifest = {"engine": engine, "model": model, "language": language}
        click.echo(f"Transcribing {src.name} with {engine} ({model})...", err=True)
        data = transcribe(str(src), engine, model, language)
        manifest["language"] = data["language"]

        click.echo(
            f"Segmenting {len(data['words'])} words into scenes "
            f"(min={min_segment}s max={max_segment}s silence={silence}s)...",
            err=True,
        )
        segments = segment_words(
            data["words"], data["segments"], min_segment, max_segment, silence
        )
        if not segments:
            raise click.ClickException("Transcription produced no usable segments.")

        result = write_segments(str(src), manifest, segments, output_dir)

        if fmt == "text":
            out(
                {
                    "segments_file": result["segments_file"],
                    "segment_count": result["segment_count"],
                    "language": result["language"],
                },
                "text",
            )
        else:
            out(result, "json")

    return CommandManifest(name="segment", click_command=segment_cmd)
