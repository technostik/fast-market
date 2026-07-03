from __future__ import annotations

import shutil
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.normalize_volume.analysis import (
    DEFAULT_REFERENCE_CLIP_SECS,
    apply_dynamic_normalization,
    apply_flat_gain,
    compute_makeup_gain,
    download_youtube_clip,
    is_youtube_url,
    measure_mean_volume,
    residual_correction_gain,
)
from common.cli.helpers import out
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
    @click.argument("SOURCE")
    @click.option(
        "--duration", "-d",
        type=int,
        default=DEFAULT_REFERENCE_CLIP_SECS,
        help=f"When SOURCE is a YouTube URL, only download this many seconds from the "
             f"start (default: {DEFAULT_REFERENCE_CLIP_SECS}s) instead of the whole video.",
    )
    @click.option(
        "--cookies",
        type=click.Path(exists=True),
        default=None,
        help="Path to a cookies file for authenticated YouTube requests.",
    )
    def set_reference_cmd(source, duration, cookies):
        """Analyze SOURCE once and store its mean volume as the normalization target.

        SOURCE can be a local audio/video file, or a YouTube URL - in which case
        only the first --duration seconds are downloaded, not the whole video.
        """
        is_url = is_youtube_url(source)
        clip_path = None

        try:
            if is_url:
                click.echo(f"Downloading first {duration}s from {source} ...")
                clip_path = download_youtube_clip(source, duration_secs=duration, cookies=cookies)
                ref_path = clip_path
            else:
                ref_path = Path(source).resolve()
                if not ref_path.exists():
                    raise click.ClickException(f"File not found: {ref_path}")

            mean_db = measure_mean_volume(ref_path)

            data = _load_raw_tool_config()
            data["normalize_volume"] = {
                "reference_path": source if is_url else str(ref_path),
                "reference_mean_volume_db": mean_db,
            }
            save_tool_config("sound", data)
            click.echo(f"Reference volume set: {mean_db:.1f} dB (from {source})")
        finally:
            if clip_path is not None:
                shutil.rmtree(clip_path.parent, ignore_errors=True)

    @normalize_volume_cmd.command("measure")
    @click.argument("FILE", type=click.Path(exists=True, dir_okay=False))
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
    def measure_cmd(file, fmt, modal):
        """Measure FILE's current mean volume (dBFS) without changing anything."""
        path = Path(file).resolve()
        if modal:
            from commands.remote import run_remote_normalize_volume_measure
            data = run_remote_normalize_volume_measure(path)
        else:
            mean_db = measure_mean_volume(path)
            data = {"path": str(path), "mean_volume_db": mean_db}
        out(data, fmt)

    @normalize_volume_cmd.command("apply")
    @click.argument("FILE", type=click.Path(exists=True, dir_okay=False))
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default=None,
        help="Output path (default: <name>_normalized<ext> next to the input).",
    )
    @click.option(
        "--modal",
        is_flag=True,
        default=False,
        help="Run on Modal remote infrastructure.",
    )
    @click.pass_context
    def apply_cmd(ctx, file, output, modal):
        """Normalize FILE's audio volume to match the configured reference level."""
        input_path = Path(file).resolve()

        try:
            config = load_sound_config().get("normalize_volume", {})
            target_db = config.get("reference_mean_volume_db")
            if target_db is None:
                raise click.ClickException(
                    "No reference volume configured. Run: sound normalize-volume set-reference <file>"
                )

            if output:
                output_path = Path(output).resolve()
            else:
                output_path = input_path.with_name(f"{input_path.stem}_normalized{input_path.suffix}")

            if modal:
                from commands.remote import run_remote_normalize_volume_apply
                result = run_remote_normalize_volume_apply(input_path, output_path, target_db)
                current_db = result["input_volume_db"]
                makeup_gain = result["makeup_gain"]
                output_db = result["output_volume_db"]
                correction_db = result.get("correction_db")
            else:
                current_db = measure_mean_volume(input_path)
                makeup_gain = compute_makeup_gain(target_db, current_db)
                apply_dynamic_normalization(input_path, output_path, makeup_gain)
                output_db = measure_mean_volume(output_path)

                correction_db = residual_correction_gain(target_db, output_db)
                if correction_db is not None:
                    corrected_path = output_path.with_name(f".{output_path.stem}.correcting{output_path.suffix}")
                    apply_flat_gain(output_path, corrected_path, correction_db)
                    corrected_path.replace(output_path)
                    output_db = measure_mean_volume(output_path)

            click.echo(f"Input volume:   {current_db:.1f} dB")
            click.echo(f"Reference:      {target_db:.1f} dB")
            click.echo(f"Makeup gain:    {makeup_gain:.2f}x")
            if correction_db is not None:
                click.echo(f"Correction:     {correction_db:+.1f} dB (compressor overshoot correction)")
            click.echo(f"Output volume:  {output_db:.1f} dB")
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
