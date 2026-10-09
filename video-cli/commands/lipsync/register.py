from __future__ import annotations

import json
import time
from pathlib import Path

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    from commands.lipsync import sadtalker as _st

    @click.command("lipsync")
    @click.argument("photo", required=False, type=click.Path(exists=True, dir_okay=False))
    @click.argument("audio", required=False, type=click.Path(exists=True, dir_okay=False))
    @click.option("--output", "-o", type=click.Path(), default=None,
                  help="Output MP4 path (default: <photo-stem>_talking.mp4 next to photo). "
                       "Missing parent directories are created.")
    @click.option("--engine", type=click.Choice(["sadtalker"]), default="sadtalker",
                  show_default=True, help="Lip-sync backend (only SadTalker for now).")
    @click.option("--size", type=click.Choice(["256", "512"]), default="256",
                  show_default=True,
                  help="Face render size. 256 fits ~4GB VRAM; 512 needs 12GB+.")
    @click.option("--still/--no-still", default=True, show_default=True,
                  help="Still-image mode (natural motion for a single photo).")
    @click.option("--preprocess",
                  type=click.Choice(["full", "crop", "resize"]), default="full",
                  show_default=True, help="Face preprocessing mode.")
    @click.option("--enhancer",
                  type=click.Choice(["none", "gfpgan"]), default="none",
                  show_default=True,
                  help="Face enhancer. gfpgan improves detail but needs ~8GB+ "
                       "peak VRAM; test without it first.")
    @click.option("--device", type=click.Choice(["auto", "cuda", "cpu"]), default="auto",
                  show_default=True, help="Compute device (auto = cuda if nvidia-smi exists).")
    @click.option("--sadtalker-dir", type=click.Path(), default=None,
                  help="SadTalker data home (default: ~/.local/share/fast-market/video/sadtalker).")
    @click.option("--setup", "setup_only", is_flag=True, default=False,
                  help="Install SadTalker (clone, CUDA torch venv, checkpoints) and exit.")
    @click.option("--timeout", type=float, default=900, show_default=True,
                  help="Max seconds for setup steps and inference.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["text", "json"]), default="text",
                  show_default=True, help="Output format")
    @click.option("--verbose", "-v", is_flag=True, default=False,
                  help="Stream backend logs with timings on stderr.")
    def lipsync_cmd(photo, audio, output, engine, size, still, preprocess,
                     enhancer, device, sadtalker_dir, setup_only, timeout, fmt, verbose):
        """Animate a still photo with speech audio (talking head, offline).

        Example: video lipsync portrait.png voice.wav -o talking.mp4

        First run needs --setup (downloads GBs: repo, CUDA PyTorch venv,
        checkpoints). French audio works: motion is derived from acoustics,
        not phonemes.
        """
        _start = time.monotonic()

        def _log(message: str) -> None:
            click.echo(message, err=True)

        def _vlog(message: str) -> None:
            if verbose:
                click.echo(f"[+{time.monotonic() - _start:.1f}s] {message}", err=True)

        home = Path(sadtalker_dir).expanduser() if sadtalker_dir else _st.default_home()

        if setup_only:
            try:
                _st.setup(home, _log, device=device)
            except _st.LipsyncError as exc:
                raise click.ClickException(str(exc)) from exc
            return

        if not photo or not audio:
            raise click.UsageError("PHOTO and AUDIO are required (or use --setup).")

        photo_path = Path(photo).resolve()
        if output is None:
            output_path = photo_path.parent / f"{photo_path.stem}_talking.mp4"
        else:
            output_path = Path(output)
            if not output_path.is_absolute():
                output_path = Path.cwd() / output_path

        size_int = int(size)
        eff_device = _st.resolve_device(device)
        _log(f"lipsync via SadTalker (size={size_int}, still={still}, "
             f"enhancer={enhancer}, device={eff_device}) …")
        try:
            out = _st.run_lipsync(
                photo=str(photo_path),
                audio=str(Path(audio).resolve()),
                output=output_path,
                home=home,
                size=size_int,
                still=still,
                preprocess=preprocess,
                enhancer=enhancer,
                device=device,
                timeout=timeout,
                progress_cb=_log if verbose else (lambda _m: None),
            )
        except _st.LipsyncError as exc:
            raise click.ClickException(str(exc)) from exc
        _vlog(f"done in {time.monotonic() - _start:.1f}s")
        if fmt == "json":
            click.echo(json.dumps({
                "path": out,
                "engine": engine,
                "photo": str(photo_path),
                "audio": str(Path(audio).resolve()),
                "size": size_int,
                "still": still,
                "enhancer": enhancer,
                "device": eff_device,
            }))
        else:
            click.echo(out)

    return CommandManifest(name="lipsync", click_command=lipsync_cmd)
