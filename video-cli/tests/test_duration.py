"""Tests for the `video duration` CLI command."""

import subprocess
import sys
from pathlib import Path

import click
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.duration.register import get_duration


def _make_test_video(path: Path, duration: float = 3.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c=blue:s=128x72:d={duration}:r=10",
            "-c:v", "libx264", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_get_duration_returns_seconds(tmp_path: Path):
    src = tmp_path / "src.mp4"
    _make_test_video(src, duration=3.0)
    assert 2.5 <= get_duration(str(src)) <= 3.5


def test_get_duration_raises_on_non_media_file(tmp_path: Path):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_text("not a video")
    with pytest.raises(RuntimeError):
        get_duration(str(bogus))


def test_cli_outputs_seconds(tmp_path: Path, capsys):
    from commands.duration.register import register

    src = tmp_path / "src.mp4"
    _make_test_video(src, duration=2.0)
    manifest = register({})
    assert manifest.name == "duration"
    ctx = click.Context(manifest.click_command)
    with ctx:
        ctx.invoke(manifest.click_command, input_file=str(src))
    out = capsys.readouterr().out.strip()
    assert 1.5 <= float(out) <= 2.5


def test_cli_fails_on_bad_file(tmp_path: Path):
    from commands.duration.register import register

    bogus = tmp_path / "bogus.mp4"
    bogus.write_text("not a video")
    manifest = register({})
    with pytest.raises(click.ClickException):
        manifest.click_command.main([str(bogus)], standalone_mode=False)
