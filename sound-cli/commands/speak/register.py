from __future__ import annotations

import sys
import time
from pathlib import Path

import click
import soundfile as sf

from commands.base import CommandManifest
from commands.helpers import build_engine
from common.cli.helpers import out
from core.config import load_sound_config
from core.models import TTSResult
from plugins.base import TTSPlugin


def register(plugin_manifests: dict) -> CommandManifest:
    engine_choices = [
        n for n, m in plugin_manifests.items()
        if issubclass(m.engine_class, TTSPlugin)
    ]

    @click.command("speak")
    @click.argument("TEXT", required=False)
    @click.option(
        "--file", "-f",
        type=click.Path(exists=True, dir_okay=False),
        default=None,
        help="Read text from a file (alternative to TEXT arg / piping)",
    )
    @click.option(
        "--engine", "-e",
        type=click.Choice(engine_choices),
        default=None,
        help="TTS engine to use",
    )
    @click.option(
        "--voice", "-v",
        default=None,
        help=(
            "Voice specification. "
            "For kokoro: voice name(s) with weights, "
            "e.g. 'am_michael*0.7,am_fenrir*0.3'. "
            "For qwen3: natural language voice description, "
            "e.g. 'A warm, friendly male voice'."
        ),
    )
    @click.option(
        "--speed", "-s",
        type=float,
        default=None,
        help="Playback speed (default: 1.0, kokoro only)",
    )
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default=None,
        help="Output file path (default: workdir/speak_<timestamp>.wav)",
    )
    @click.option(
        "--language", "-L",
        default=None,
        help="Language for qwen3 engine (e.g. English, Chinese, French)",
    )
    @click.option(
        "--format", "-F", "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format",
    )
    @click.pass_context
    def speak_cmd(ctx, text, file, engine, voice, speed, output, language, fmt):
        """Synthesize speech from TEXT.

        TEXT can be provided as a positional argument, read from a file
        (--file), or piped via stdin.
        """
        # --- resolve text source ------------------------------------------------
        if file:
            text = Path(file).read_text(encoding="utf-8").strip()
        elif text:
            pass
        elif not sys.stdin.isatty():
            text = sys.stdin.read().strip()

        if not text:
            click.echo(
                "Error: No text provided. Pass TEXT argument, --file, or pipe input.",
                err=True,
            )
            ctx.exit(1)

        # --- load config & engines ------------------------------------------------
        config = load_sound_config()

        plugins = build_engine(config, tool_root=Path(__file__).resolve().parents[2])
        if not plugins:
            click.echo("Error: No engines available.", err=True)
            ctx.exit(1)

        actual_engine = engine or config.get("default_engine", "kokoro")
        if actual_engine not in plugins:
            click.echo(
                f"Error: Unknown engine '{actual_engine}'. "
                f"Available: {', '.join(plugins.keys())}",
                err=True,
            )
            ctx.exit(1)

        engine_config = config.get(actual_engine, {})
        actual_voice = voice or engine_config.get("voice", "")
        actual_speed = speed if speed is not None else engine_config.get("speed", 1.0)
        actual_language = language or engine_config.get("language", "English")

        plugin = plugins[actual_engine]

        try:
            audio, sr = plugin.synthesize(
                text=text,
                voice=actual_voice,
                speed=actual_speed,
                language=actual_language,
                clone=engine_config.get("clone"),
                ref_text=engine_config.get("ref_text"),
            )

            workdir = config.get("workdir") or "."
            output_dir = Path(workdir)

            if output:
                output_path = Path(output)
            else:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output_path = output_dir / f"speak_{timestamp}.wav"

            output_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(output_path), audio.numpy(), sr)

            duration = len(audio) / sr if len(audio) > 0 else 0.0

            result = TTSResult(
                path=output_path,
                text=text,
                voice=actual_voice,
                engine=actual_engine,
                duration_secs=round(duration, 2),
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
        speak_cmd.params.extend(pm.cli_options.get("speak", []))
    for pm in plugin_manifests.values():
        speak_cmd.params.extend(pm.cli_options.get("*", []))

    return CommandManifest(name="speak", click_command=speak_cmd)
