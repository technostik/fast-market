from __future__ import annotations

import tempfile
from pathlib import Path

import click

from commands.base import CommandManifest

_DEFAULT_CLIP = Path(__file__).parents[2] / "tests/fixtures/publish/test_clip.mkv"


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("modal-diagnose")
    @click.option("--full", is_flag=True, help="Also upload a clip, process it with ffmpeg, and download the result.")
    @click.option("--clip", type=click.Path(exists=True), default=None, help="Clip to use for --full (default: test fixture).")
    def modal_diagnose_cmd(full: bool, clip: str | None):
        """Test Modal API connectivity and inspect the remote environment."""
        try:
            from modal_client.app import app
            from modal_client.diagnose import run_diagnose, run_file_roundtrip
            from modal_client.remote_steps import run_media_pipeline
        except ImportError as e:
            raise click.ClickException(f"modal not installed: {e}")

        click.echo("Connecting to Modal...", err=True)
        with app.run():
            # ── Step 1: environment check ──────────────────────────────────
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

                # ── Step 2: file roundtrip (ffmpeg remux) ──────────────────
                click.echo(f"\nUploading {clip_path.name} ({size_kb:.1f} KB)...", err=True)
                rt = run_file_roundtrip.remote(video_bytes, clip_path.name)

                with tempfile.NamedTemporaryFile(
                    suffix=".mp4", prefix="modal_out_", delete=False
                ) as tmp:
                    tmp.write(rt["output_bytes"])
                    roundtrip_path = tmp.name

                click.echo("File roundtrip (ffmpeg remux):")
                click.echo(f"  uploaded:   {rt['input_size'] / 1024:.1f} KB  ({rt['input_format']})")
                click.echo(f"  downloaded: {rt['output_size'] / 1024:.1f} KB  ({rt['output_format']})")
                click.echo(f"  duration:   {rt['duration']}s")
                click.echo(f"  saved to:   {roundtrip_path}")

                # ── Step 3: full media pipeline (silence + whisper + subs) ─
                click.echo(f"\nRunning full media pipeline on {clip_path.name}...", err=True)
                pipeline = run_media_pipeline.remote(
                    video_bytes,
                    clip_path.name,
                    do_remove_silence=True,
                    threshold=-65.0,
                    do_transcribe=True,
                    ass_bytes=None,
                    do_burn_subtitles=True,
                    language="fr",
                    model_size="tiny",   # tiny for speed in diagnostics
                    subtitle_size=96,
                )

                with tempfile.NamedTemporaryFile(
                    suffix=".mp4", prefix="modal_pipeline_", delete=False
                ) as tmp:
                    tmp.write(pipeline["video_bytes"])
                    pipeline_video_path = tmp.name

                with tempfile.NamedTemporaryFile(
                    suffix=".ass", prefix="modal_pipeline_", delete=False, mode="wb"
                ) as tmp:
                    tmp.write(pipeline["ass_bytes"])
                    pipeline_ass_path = tmp.name

                click.echo("Full pipeline result:")
                click.echo(f"  input:       {size_kb:.1f} KB")
                if pipeline["original_duration"] is not None:
                    click.echo(f"  after silence removal: {pipeline['final_duration']:.1f}s  (was {pipeline['original_duration']:.1f}s)")
                click.echo(f"  output video: {len(pipeline['video_bytes']) / 1024:.1f} KB  → {pipeline_video_path}")
                click.echo(f"  subtitle (.ass): {len(pipeline['ass_bytes']) / 1024:.1f} KB  → {pipeline_ass_path}")
                if pipeline["ass_txt"]:
                    preview = pipeline["ass_txt"][:120].replace("\n", " ")
                    click.echo(f"  transcript preview: {preview}…")

    return CommandManifest(name="modal-diagnose", click_command=modal_diagnose_cmd)
