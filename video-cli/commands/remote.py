from __future__ import annotations

from pathlib import Path

import click


def run_remote_remove_silence(input_path: Path, output_path: Path, threshold: float) -> dict:
    try:
        from modal_client.app import app, spawn_and_get
        from modal_client.remote_steps import remote_remove_silence
    except ImportError as exc:
        raise click.ClickException(f"modal not installed: {exc}") from exc
    click.echo("Running remove-silence on Modal...", err=True)
    with app.run():
        result = spawn_and_get(
            remote_remove_silence, input_path.read_bytes(), input_path.name, threshold
        )
    output_path.write_bytes(result["video_bytes"])
    return result


def run_remote_extract_transcript(
    input_path: Path,
    output_path: Path,
    fmt: str,
    language: str,
    model: str,
    font_size: int,
    use_groq: bool = False,
) -> dict:
    try:
        from modal_client.app import app, spawn_and_get
        from modal_client.remote_steps import remote_extract_transcript
    except ImportError as exc:
        raise click.ClickException(f"modal not installed: {exc}") from exc
    click.echo("Running extract-transcript on Modal...", err=True)
    with app.run():
        result = spawn_and_get(
            remote_extract_transcript,
            input_path.read_bytes(), input_path.name, language, model, font_size, use_groq, fmt,
        )
    if fmt in {"srt", "txt"}:
        output_path.write_bytes(result.get("transcript_bytes", b""))
    else:
        output_path.write_bytes(result["ass_bytes"])
    return result


def run_remote_burn_subtitles(video_path: Path, ass_path: Path, output_path: Path, font_size: int) -> dict:
    try:
        from modal_client.app import app, spawn_and_get
        from modal_client.remote_steps import remote_burn_subtitles
    except ImportError as exc:
        raise click.ClickException(f"modal not installed: {exc}") from exc
    click.echo("Running burn-subtitles on Modal...", err=True)
    with app.run():
        result = spawn_and_get(
            remote_burn_subtitles,
            video_path.read_bytes(), video_path.name, ass_path.read_bytes(), font_size,
        )
    output_path.write_bytes(result["video_bytes"])
    return result


def run_remote_concat_videos(input_paths: list[Path], output_path: Path) -> dict:
    try:
        from modal_client.app import app, spawn_and_get
        from modal_client.remote_steps import remote_concat_videos
    except ImportError as exc:
        raise click.ClickException(f"modal not installed: {exc}") from exc
    click.echo("Running concat on Modal...", err=True)
    video_bytes_list = [p.read_bytes() for p in input_paths]
    video_names = [p.name for p in input_paths]
    with app.run():
        result = spawn_and_get(remote_concat_videos, video_bytes_list, video_names)
    output_path.write_bytes(result["video_bytes"])
    return result
