"""Chrome WebM files omit the container duration. MoviePy must still open them."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from commands.duration.register import get_duration
from commands.media_open import open_video_clip


def _live_webm(path: Path, duration: float = 2.0) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x120:d={duration}:r=10",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libvpx-vp9", "-b:v", "200k",
            "-c:a", "libopus",
            "-shortest",
            "-f", "webm", "-live", "1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.fail(result.stderr[-500:])


def test_get_duration_reads_packet_timestamps_when_header_has_none(tmp_path: Path):
    src = tmp_path / "live.webm"
    _live_webm(src)
    assert 1.5 <= get_duration(str(src)) <= 2.5


def test_open_video_clip_reads_durationless_webm(tmp_path: Path):
    import moviepy.video.io.ffmpeg_reader as video_reader

    src = tmp_path / "live.webm"
    _live_webm(src)
    original = video_reader.ffmpeg_parse_infos
    clip = open_video_clip(str(src))
    try:
        assert 1.5 <= clip.duration <= 2.5
        assert clip.get_frame(0.2).shape == (120, 160, 3)
        assert clip.audio is not None
    finally:
        clip.close()
    assert video_reader.ffmpeg_parse_infos is original


def test_open_video_clip_still_opens_mp4(tmp_path: Path):
    src = tmp_path / "plain.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "color=c=red:s=160x120:d=1:r=10",
            "-c:v", "libx264", str(src),
        ],
        capture_output=True, text=True, check=True,
    )
    clip = open_video_clip(str(src))
    try:
        assert 0.5 <= clip.duration <= 1.5
    finally:
        clip.close()


def test_open_video_clip_rejects_non_media(tmp_path: Path):
    import moviepy.video.io.ffmpeg_reader as video_reader

    bogus = tmp_path / "bogus.webm"
    bogus.write_text("not a video")
    original = video_reader.ffmpeg_parse_infos
    with pytest.raises(OSError):
        open_video_clip(str(bogus))
    assert video_reader.ffmpeg_parse_infos is original
