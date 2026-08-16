from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest


def parse_timestamp(ts: str) -> float | None:
    """Parse a cut point into seconds.

    Accepts ``MM:SS``, ``HH:MM:SS``, or a bare number of seconds.
    Returns ``None`` for an unparseable value.
    """
    ts = (ts or "").strip()
    if not ts:
        return None
    if ":" in ts:
        parts: list[float] = []
        for p in ts.split(":"):
            try:
                parts.append(float(p))
            except ValueError:
                return None
        if not parts:
            return None
        parts.reverse()
        seconds = 0.0
        for i, v in enumerate(parts):
            seconds += v * (60 ** i)
        return seconds
    try:
        return float(ts)
    except ValueError:
        return None


def cut_video(input_file: str, output_file: str, seconds: float, keep: str = "head") -> str:
    """Trim a video at ``seconds`` using ffmpeg stream copy (no re-encode).

    ``keep="head"`` keeps ``[0, seconds]`` (truncates the tail).
    ``keep="tail"`` keeps ``[seconds, end]`` (drops the head).
    """
    import subprocess

    input_path = Path(input_file).resolve()
    output_path = Path(output_file).resolve()

    cmd: list[str] = ["ffmpeg", "-y"]
    if keep == "tail":
        cmd += ["-ss", f"{seconds:.3f}"]
    cmd += ["-i", str(input_path)]
    if keep == "head":
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-c", "copy", str(output_path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg cut failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return str(output_path)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("cut")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
    @click.option(
        "--time", "-t",
        required=True,
        help="Cut point as MM:SS, HH:MM:SS, or seconds (e.g. 1:30 = 90s)",
    )
    @click.option(
        "--keep",
        type=click.Choice(["head", "tail"]),
        default="head",
        show_default=True,
        help="head: keep [0,time] and drop the tail; tail: keep [time,end] and drop the head",
    )
    def cut_cmd(input_file: str, output: str | None, time: str, keep: str):
        """Trim a video at a timestamp (fast, stream copy). Keeps the head by default."""
        seconds = parse_timestamp(time)
        if seconds is None:
            raise click.BadParameter(f"Invalid time format: {time!r} (use MM:SS or seconds)")

        input_path = Path(input_file).resolve()
        output_path = (
            Path(output).resolve() if output
            else input_path.parent / f"{input_path.stem}_cut{input_path.suffix}"
        )

        click.echo(f"Cutting {input_path.name} at {time} (keep={keep})...", err=True)
        out = cut_video(str(input_path), str(output_path), seconds, keep)
        click.echo(str(out))

    return CommandManifest(name="cut", click_command=cut_cmd)
