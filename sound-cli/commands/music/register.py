from __future__ import annotations

import time
from pathlib import Path

import click
import soundfile as sf

from commands.base import CommandManifest
from commands.helpers import build_engine
from common.cli.helpers import out
from core.config import load_sound_config
from core.models import MusicGenResult
from plugins.base import MusicGenPlugin


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
        help="Music generation engine",
    )
    @click.option(
        "--duration", "-d",
        type=float,
        default=None,
        help="Duration in seconds (default: 5.0)",
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
    def music_cmd(ctx, prompt, engine, duration, output, fmt):
        """Generate music from a text PROMPT."""
        config = load_sound_config()

        plugins = build_engine(config, tool_root=Path(__file__).resolve().parents[2])
        if not plugins:
            click.echo("Error: No engines available.", err=True)
            ctx.exit(1)

        actual_engine = engine or "musicgen"
        if actual_engine not in plugins:
            click.echo(
                f"Error: Unknown engine '{actual_engine}'. "
                f"Available: {', '.join(plugins.keys())}",
                err=True,
            )
            ctx.exit(1)

        engine_config = config.get(actual_engine, {})
        actual_duration = duration if duration is not None else engine_config.get("duration", 5.0)

        plugin = plugins[actual_engine]

        try:
            audio, sr = plugin.generate(
                prompt=prompt,
                duration=actual_duration,
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
