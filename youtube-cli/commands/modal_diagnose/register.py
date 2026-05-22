from __future__ import annotations

import tempfile
from pathlib import Path

import click

from commands.base import CommandManifest

_DEFAULT_CLIP = Path(__file__).parents[2] / "tests/fixtures/publish/test_clip.mkv"


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("modal-diagnose")
    @click.option("--full", is_flag=True, help="Also upload a clip, process it with ffmpeg, and download the result.")
    @click.option("--clip", type=click.Path(exists=True), default=None, help=f"Clip to use for --full (default: test fixture).")
    def modal_diagnose_cmd(full: bool, clip: str | None):
        """Test Modal API connectivity and inspect the remote environment."""
        try:
            from modal_client.app import app
            from modal_client.diagnose import run_diagnose, run_file_roundtrip
        except ImportError as e:
            raise click.ClickException(f"modal not installed: {e}")

        click.echo("Connecting to Modal...", err=True)
        with app.run():
            result = run_diagnose.remote()
            click.echo("Remote environment:")
            for key, value in result.items():
                click.echo(f"  {key}: {value}")

            if full:
                clip_path = Path(clip) if clip else _DEFAULT_CLIP
                if not clip_path.exists():
                    raise click.ClickException(f"Clip not found: {clip_path}")

                video_bytes = clip_path.read_bytes()
                size_kb = len(video_bytes) / 1024
                click.echo(f"\nUploading {clip_path.name} ({size_kb:.1f} KB)...", err=True)

                rt = run_file_roundtrip.remote(video_bytes, clip_path.name)

                with tempfile.NamedTemporaryFile(
                    suffix=".mp4", prefix="modal_out_", delete=False
                ) as tmp:
                    tmp.write(rt["output_bytes"])
                    out_path = tmp.name

                click.echo("File roundtrip:")
                click.echo(f"  uploaded:  {rt['input_size'] / 1024:.1f} KB  ({rt['input_format']})")
                click.echo(f"  downloaded: {rt['output_size'] / 1024:.1f} KB  ({rt['output_format']})")
                click.echo(f"  duration:  {rt['duration']}s")
                click.echo(f"  saved to:  {out_path}")

    return CommandManifest(name="modal-diagnose", click_command=modal_diagnose_cmd)
