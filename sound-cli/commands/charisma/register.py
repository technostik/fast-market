from __future__ import annotations

import json
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.charisma.analysis import score_charisma
from commands.prosody.analysis import load_audio
from common.cli.helpers import out
from core.models import CharismaResult


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("charisma")
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
    @click.option(
        "--modal",
        is_flag=True,
        default=False,
        help="Run on Modal remote infrastructure.",
    )
    @click.pass_context
    def charisma_cmd(ctx, file, output, fmt, modal):
        """Estimate the vocal charisma of an audio or video FILE.

        Combines prosody (70%), voice quality (20%), and expressiveness (10%)
        signals into a 0-100 score with a per-dimension breakdown. Runs fully
        offline via acoustic signal analysis - see sound-cli/AGENTS.md for what
        each subscore approximates and its limitations."""
        input_path = Path(file).resolve()

        try:
            if modal:
                from commands.remote import run_remote_charisma
                data = run_remote_charisma(input_path)
            else:
                y, sr = load_audio(input_path)
                scores = score_charisma(y, sr)
                result = CharismaResult(path=input_path, **scores)
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

    return CommandManifest(name="charisma", click_command=charisma_cmd)
