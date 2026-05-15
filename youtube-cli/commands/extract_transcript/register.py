from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest


def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_to_srt(
    input_path: str,
    output_path: str,
    language: str = "fr",
    model_size: str = "large-v3",
) -> None:
    """Transcribe a video file to SRT using faster_whisper (fallback: openai-whisper)."""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        lang = language if language != "auto" else None
        segments_gen, _ = model.transcribe(input_path, language=lang)
        segments = [(seg.start, seg.end, seg.text.strip()) for seg in segments_gen]
    except ImportError:
        import whisper  # type: ignore[import]

        model = whisper.load_model(model_size)
        lang = language if language != "auto" else None
        result = model.transcribe(input_path, language=lang)
        segments = [
            (seg["start"], seg["end"], seg["text"].strip())
            for seg in result["segments"]
        ]

    with open(output_path, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}\n")
            f.write(f"{text}\n\n")


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("extract-transcript")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output SRT file path")
    @click.option("--language", "-l", default="fr", show_default=True, help="Language code or 'auto'")
    @click.option("--model", "-m", default="large-v3", show_default=True, help="Whisper model size")
    def extract_transcript_cmd(
        input_file: str,
        output: str | None,
        language: str,
        model: str,
    ):
        """Transcribe a video file to SRT subtitles using Whisper."""
        input_path = Path(input_file).resolve()
        if output:
            output_path = Path(output).resolve()
        else:
            output_path = input_path.parent / f"{input_path.stem}.srt"

        click.echo(f"Transcribing {input_path.name} ({model}, {language})...", err=True)
        transcribe_to_srt(str(input_path), str(output_path), language, model)
        click.echo(str(output_path))

    return CommandManifest(name="extract-transcript", click_command=extract_transcript_cmd)
