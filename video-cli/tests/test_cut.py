"""Smoke test for the `video cut` CLI (ffmpeg stream copy)."""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.cut.register import cut_video, parse_timestamp


def _make_test_video(path: Path, duration: float = 3.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c=blue:s=128x72:d={duration}:r=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_parse_timestamp_cli():
    assert parse_timestamp("2:00") == 120.0
    assert parse_timestamp("bad") is None


def test_cut_video_head(tmp_path: Path):
    src = tmp_path / "src.mp4"
    _make_test_video(src, duration=3.0)
    out = tmp_path / "out.mp4"
    cut_video(str(src), str(out), 1.5, keep="head")
    assert out.exists()
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert 1.4 <= float(probe.stdout.strip()) <= 2.0


def test_cut_video_tail(tmp_path: Path):
    src = tmp_path / "src.mp4"
    _make_test_video(src, duration=3.0)
    out = tmp_path / "out.mp4"
    cut_video(str(src), str(out), 1.0, keep="tail")
    assert out.exists()
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert 1.9 <= float(probe.stdout.strip()) <= 2.2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
