from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("pipeline")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Final subtitled output path")
    @click.option("--workdir", type=click.Path(file_okay=False), default=None, help="Directory for intermediate files")
    @click.option("--threshold", "-t", default=-65.0, show_default=True, help="Silence threshold in dB")
    @click.option("--language", "-l", default="fr", show_default=True, help="Language code or 'auto'")
    @click.option("--model", "-m", default="medium", show_default=True, help="Whisper model size")
    @click.option("--font-size", default=96, show_default=True, help="Subtitle font size")
    @click.option("--modal/--local", default=False, show_default=True, help="Run all media steps on Modal instead of locally")
    def pipeline_cmd(
        input_file: str,
        output: str | None,
        workdir: str | None,
        threshold: float,
        language: str,
        model: str,
        font_size: int,
        modal: bool,
    ):
        """Run remove-silence -> extract-transcript -> burn-subtitles."""
        input_path = Path(input_file).resolve()
        d = Path(workdir).resolve() if workdir else input_path.parent
        d.mkdir(parents=True, exist_ok=True)
        no_silence = d / f"{input_path.stem}_nosilence.mp4"
        ass_path = d / f"{input_path.stem}.ass"
        output_path = Path(output).resolve() if output else d / f"{input_path.stem}_subtitled.mp4"

        if modal:
            try:
                from modal_client.app import app
                from modal_client.remote_steps import run_media_pipeline
            except ImportError as exc:
                raise click.ClickException(f"modal not installed: {exc}") from exc
            click.echo("Running full video pipeline on Modal...", err=True)
            with app.run():
                result = run_media_pipeline.remote(
                    input_path.read_bytes(), input_path.name, True, threshold,
                    True, None, True, language, model, font_size, False,
                )
            output_path.write_bytes(result["video_bytes"])
            if result.get("ass_bytes"):
                ass_path.write_bytes(result["ass_bytes"])
        else:
            from commands.remove_silence.register import remove_silence_simple
            from commands.extract_transcript.register import generate_karaoke_ass
            from commands.burn_subtitles.register import burn_ass_subtitles
            click.echo("Removing silence...", err=True)
            remove_silence_simple(str(input_path), str(no_silence), threshold, progress_cb=None)
            click.echo("Extracting transcript...", err=True)
            generate_karaoke_ass(str(no_silence), str(ass_path), language, model, font_size, progress_cb=None)
            click.echo("Burning subtitles...", err=True)
            burn_ass_subtitles(str(no_silence), str(ass_path), str(output_path), font_size, progress_cb=None)

        click.echo(str(output_path))

    return CommandManifest(name="pipeline", click_command=pipeline_cmd)
