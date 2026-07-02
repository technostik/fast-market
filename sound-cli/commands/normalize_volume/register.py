from __future__ import annotations

from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.normalize_volume.analysis import (
    apply_dynamic_normalization,
    compute_makeup_gain,
    measure_mean_volume,
)
from common.core.config import save_tool_config
from common.core.paths import get_tool_config
from core.config import load_sound_config


def _load_raw_tool_config() -> dict:
    path = get_tool_config("sound")
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("normalize-volume", invoke_without_command=True)
    @click.pass_context
    def normalize_volume_cmd(ctx):
        """Normalize a video's volume dynamically against a configured reference level."""
        if ctx.invoked_subcommand is not None:
            return

        config = load_sound_config().get("normalize_volume", {})
        if "reference_mean_volume_db" not in config:
            click.echo("No reference volume configured.")
            click.echo("Run: sound normalize-volume set-reference <file>")
            return

        click.echo(f"Reference file: {config.get('reference_path')}")
        click.echo(f"Reference mean volume: {config['reference_mean_volume_db']:.1f} dB")

    @normalize_volume_cmd.command("set-reference")
    @click.argument("FILE", type=click.Path(exists=True, dir_okay=False))
    def set_reference_cmd(file):
        """Analyze FILE once and store its mean volume as the normalization target."""
        ref_path = Path(file).resolve()
        mean_db = measure_mean_volume(ref_path)

        data = _load_raw_tool_config()
        data["normalize_volume"] = {
            "reference_path": str(ref_path),
            "reference_mean_volume_db": mean_db,
        }
        save_tool_config("sound", data)
        click.echo(f"Reference volume set: {mean_db:.1f} dB (from {ref_path})")

    @normalize_volume_cmd.command("apply")
    @click.argument("FILE", type=click.Path(exists=True, dir_okay=False))
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default=None,
        help="Output path (default: <name>_normalized<ext> next to the input).",
    )
    @click.pass_context
    def apply_cmd(ctx, file, output):
        """Normalize FILE's audio volume to match the configured reference level."""
        input_path = Path(file).resolve()

        try:
            config = load_sound_config().get("normalize_volume", {})
            target_db = config.get("reference_mean_volume_db")
            if target_db is None:
                raise click.ClickException(
                    "No reference volume configured. Run: sound normalize-volume set-reference <file>"
                )

            current_db = measure_mean_volume(input_path)
            makeup_gain = compute_makeup_gain(target_db, current_db)

            if output:
                output_path = Path(output).resolve()
            else:
                output_path = input_path.with_name(f"{input_path.stem}_normalized{input_path.suffix}")

            apply_dynamic_normalization(input_path, output_path, makeup_gain)

            click.echo(f"Input volume:   {current_db:.1f} dB")
            click.echo(f"Reference:      {target_db:.1f} dB")
            click.echo(f"Makeup gain:    {makeup_gain:.2f}x")
            click.echo(f"Output written: {output_path}")

        except click.ClickException:
            raise
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            if ctx.obj.get("verbose"):
                import traceback
                traceback.print_exc()
            ctx.exit(1)

    return CommandManifest(name="normalize-volume", click_command=normalize_volume_cmd)
