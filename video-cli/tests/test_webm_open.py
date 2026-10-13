"""Chrome WebM files omit the container duration. MoviePy must still open them."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from commands.duration.register import get_duration
from commands.media_open import (
    _parse_rate,
    container_fps_override,
    open_video_clip,
)


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


# ── VFR fps guard ─────────────────────────────────────────────────────────────
# Regression: a stream-copy cut of a VFR file gets a computed average fps far
# below the container rate (e.g. 10 fps over a static stretch of a 30 fps
# file). MoviePy adopted that average, misindexed frames (int(fps*t)) and
# re-encoded in slow motion with normal-speed audio.

@pytest.mark.parametrize(
    ("text", "expected"),
    [("30/1", 30.0), ("359/12", 359 / 12), ("0/0", None), ("", None), ("bogus", None)],
)
def test_parse_rate(text, expected):
    assert _parse_rate(text) == expected


@pytest.mark.parametrize(
    ("r_frame_rate", "avg_frame_rate", "expected"),
    [
        (30.0, 10.34, 30.0),    # VFR: force the container rate
        (29.92, 29.92, None),   # CFR: untouched
        (30.0, 30.5, None),     # <5% jitter: untouched
        (30.0, None, None),     # unknown average: MoviePy already uses r
        (None, 10.0, None),     # unknown container rate: nothing to force
        (None, None, None),
    ],
)
def test_container_fps_override(r_frame_rate, avg_frame_rate, expected):
    assert container_fps_override(r_frame_rate, avg_frame_rate) == expected


def test_remote_mirror_agrees_with_local_guard():
    """The Modal worker duplicates the decision: keep both copies in sync."""
    from modal_client.remote_steps import _container_fps_override as remote_decide

    cases = [(30.0, 10.34), (29.92, 29.92), (30.0, None), (None, 10.0)]
    for r_frame_rate, avg_frame_rate in cases:
        assert remote_decide(r_frame_rate, avg_frame_rate) == container_fps_override(
            r_frame_rate, avg_frame_rate
        )


def _cfr_mp4(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "color=c=red:s=160x120:d=1:r=10",
            "-c:v", "libx264", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_open_video_clip_forces_container_fps_on_vfr(tmp_path: Path, monkeypatch):
    """Simulates the trigger condition (r=30 container, ~10 fps average after
    a stream-copy cut of VFR): both clip and reader fps must be forced.

    (The rates are mocked because ffmpeg's muxer heuristics for r_frame_rate
    are not reproducible with lavfi sources; the decision + application path
    is what this guards.)
    """
    import commands.media_open as media_open

    src = tmp_path / "plain.mp4"
    _cfr_mp4(src)
    monkeypatch.setattr(media_open, "_probe_frame_rates", lambda path: (30.0, 10.23))
    clip = open_video_clip(str(src))
    try:
        assert clip.fps == pytest.approx(30.0)
        assert clip.reader.fps == pytest.approx(30.0)
    finally:
        clip.close()


def test_open_video_clip_leaves_cfr_fps_untouched(tmp_path: Path):
    src = tmp_path / "plain.mp4"
    _cfr_mp4(src)
    clip = open_video_clip(str(src))
    try:
        assert clip.fps == pytest.approx(10.0)
        assert 0.5 <= clip.duration <= 1.5
    finally:
        clip.close()
