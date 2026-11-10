from __future__ import annotations

import time
from pathlib import Path

import click
import soundfile as sf

from commands.base import CommandManifest
from commands.helpers import build_engine, resolve_music_engine
from common.cli.helpers import out
from core.config import load_sound_config
from core.models import MusicGenResult
from plugins.base import MusicGenPlugin


def _resolve_lyrics(
    lyrics: str | None,
    lyrics_file: str | None,
    instrumental: bool,
) -> str | None:
    """Turn the CLI lyric options into one lyrics string.

    Returns None when the engine should use its own default.
    """
    if lyrics and lyrics_file:
        raise ValueError("Use either --lyrics or --lyrics-file, not both.")

    value = lyrics
    if lyrics_file:
        value = Path(lyrics_file).read_text(encoding="utf-8").strip()

    if instrumental:
        if value:
            raise ValueError(
                "Use either --lyrics/--lyrics-file or --instrumental, not both."
            )
        return "[Instrumental]"

    return value or None


def register(plugin_manifests: dict) -> CommandManifest:
    engine_choices = [
        n for n, m in plugin_manifests.items()
        if issubclass(m.engine_class, MusicGenPlugin)
    ]

    @click.command("music")
    @click.argument("PROMPT")
    @click.option(
        "--engine", "-e",
        type=click.Choice(engine_choices),
        default=None,
        help="Music generation engine (default: default_music_engine, else acestep)",
    )
    @click.option(
        "--duration", "-d",
        type=float,
        default=None,
        help="Duration in seconds (default: per-engine config)",
    )
    @click.option(
        "--lyrics", "-l",
        default=None,
        help="Lyrics to sing, with section tags such as [Verse]/[Chorus]",
    )
    @click.option(
        "--lyrics-file",
        type=click.Path(exists=True, dir_okay=False),
        default=None,
        help="Read lyrics from a file",
    )
    @click.option(
        "--instrumental", "-i",
        is_flag=True,
        default=False,
        help="Force an instrumental track (lyrics='[Instrumental]')",
    )
    @click.option(
        "--seed", "-S",
        type=int,
        default=None,
        help="Random seed for reproducible generation",
    )
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default=None,
        help="Output file path (default: workdir/music_<timestamp>.wav)",
    )
    @click.option(
        "--format", "-F", "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format",
    )
    @click.pass_context
    def music_cmd(
        ctx, prompt, engine, duration, lyrics, lyrics_file, instrumental, seed,
        output, fmt,
    ):
        """Generate music from a text PROMPT."""
        config = load_sound_config()

        plugins = build_engine(config, tool_root=Path(__file__).resolve().parents[2])
        music_engines = {
            name: plugin
            for name, plugin in plugins.items()
            if isinstance(plugin, MusicGenPlugin)
        }
        if not music_engines:
            click.echo("Error: No music engines available.", err=True)
            ctx.exit(1)

        try:
            actual_engine = resolve_music_engine(
                config, engine, list(music_engines)
            )
            actual_lyrics = _resolve_lyrics(lyrics, lyrics_file, instrumental)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)

        engine_config = config.get(actual_engine, {})
        actual_duration = (
            duration if duration is not None else engine_config.get("duration")
        )

        plugin = music_engines[actual_engine]

        try:
            audio, sr = plugin.generate(
                prompt=prompt,
                duration=actual_duration,
                lyrics=actual_lyrics,
                seed=seed,
                verbose=bool(ctx.obj.get("verbose")),
            )

            workdir = config.get("workdir") or "."
            output_dir = Path(workdir)

            if output:
                output_path = Path(output)
            else:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output_path = output_dir / f"music_{timestamp}.wav"

            output_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(output_path), audio.numpy(), sr)

            duration_actual = len(audio) / sr if len(audio) > 0 else 0.0

            result = MusicGenResult(
                path=output_path,
                prompt=prompt,
                engine=actual_engine,
                duration_secs=round(duration_actual, 2),
                sample_rate=sr,
            )
            out(result.to_dict(), fmt)

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            if ctx.obj.get("verbose"):
                import traceback
                traceback.print_exc()
            ctx.exit(1)

    for pm in plugin_manifests.values():
        music_cmd.params.extend(pm.cli_options.get("music", []))
    for pm in plugin_manifests.values():
        music_cmd.params.extend(pm.cli_options.get("*", []))

    return CommandManifest(name="music", click_command=music_cmd)
