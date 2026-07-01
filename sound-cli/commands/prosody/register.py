from __future__ import annotations

import json
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.prosody.analysis import load_audio, score_prosody
from common.cli.helpers import out
from core.models import ProsodyResult


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("prosody")
    @click.argument("FILE", type=click.Path(exists=True, dir_okay=False))
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default=None,
        help="Also write the full JSON report to this path.",
    )
    @click.option(
        "--format", "-F", "fmt",
        type=click.Choice(["json", "text", "yaml"]),
        default="text",
        help="Output format",
    )
    @click.pass_context
    def prosody_cmd(ctx, file, output, fmt):
        """Analyze the prosody (pitch, energy, rhythm, rate) of an audio or video FILE
        and report a global 0-100 score with a per-dimension breakdown."""
        input_path = Path(file).resolve()

        try:
            y, sr = load_audio(input_path)
            scores = score_prosody(y, sr)

            result = ProsodyResult(path=input_path, **scores)
            data = result.to_dict()

            if output:
                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

            out(data, fmt)

        except click.ClickException:
            raise
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            if ctx.obj.get("verbose"):
                import traceback
                traceback.print_exc()
            ctx.exit(1)

    return CommandManifest(name="prosody", click_command=prosody_cmd)
