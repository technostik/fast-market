"""Tests for the `video short-extractor` command (16:9 -> 9:16 conversion)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.cut.register import parse_timestamp
from commands.short_extractor.register import (
    _build_fit_blur_filter,
    _crop_offset,
    extract_short,
    register,
)


def _make_landscape_video(path: Path, duration: float = 3.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c=blue:s=128x72:d={duration}:r=10",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        text=True,
    )
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return int(video["width"]), int(video["height"]), float(data["format"]["duration"])


@pytest.fixture()
def landscape_video(tmp_path: Path) -> Path:
    src = tmp_path / "source.mp4"
    _make_landscape_video(src)
    return src


def test_parse_timestamp_accepts_srt_milliseconds():
    assert parse_timestamp("00:01:12,500") == 72.5
    assert parse_timestamp("01:12.250") == 72.25


def test_crop_offset_stays_inside_frame():
    assert _crop_offset(128, 81, 0.0) == 0
    assert _crop_offset(128, 81, 1.0) == 23
    assert _crop_offset(128, 81, -1.0) == 0
    assert _crop_offset(128, 200, 1.0) == 0


def test_stack_layout_produces_nine_by_sixteen(landscape_video: Path, tmp_path: Path):
    out = tmp_path / "short.mp4"
    extract_short(str(landscape_video), str(out), 0.5, 2.5)

    width, height, duration = _probe(out)
    assert (width, height) == (72, 128)
    assert abs(width / height - 9 / 16) < 0.01
    assert 1.8 <= duration <= 2.2


def test_crop_layout_produces_nine_by_sixteen(landscape_video: Path, tmp_path: Path):
    out = tmp_path / "short.mp4"
    extract_short(str(landscape_video), str(out), 0.0, 1.0, layout="crop")

    width, height, _ = _probe(out)
    assert (width, height) == (40, 72)
    assert abs(width / height - 9 / 16) < 0.01


def test_crop_layout_with_zoom_keeps_portrait(landscape_video: Path, tmp_path: Path):
    out = tmp_path / "short.mp4"
    extract_short(
        str(landscape_video), str(out), 0.0, 1.0,
        layout="crop", zoom=1.5, center_x=0.5, center_y=0.5,
    )

    width, height, _ = _probe(out)
    assert width < height
    assert width % 2 == 0 and height % 2 == 0


def test_fit_blur_filter_builds_cover_background_and_centered_foreground():
    graph = _build_fit_blur_filter(1404, 30, 0.75)
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in graph
    assert "crop=1080:1920" in graph
    assert "gblur=sigma=30" in graph
    assert "rr=0.75:gg=0.75:bb=0.75" in graph
    assert "scale=1404:-2" in graph
    assert "overlay=(W-w)/2:(H-h)/2" in graph


def test_fit_blur_layout_outputs_1080x1920(landscape_video: Path, tmp_path: Path):
    out = tmp_path / "short.mp4"
    extract_short(str(landscape_video), str(out), 0.5, 1.5, layout="fit-blur")

    width, height, duration = _probe(out)
    assert (width, height) == (1080, 1920)
    assert 0.8 <= duration <= 1.2
    has_audio = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert has_audio == "aac"


def test_fit_blur_zoom_widens_the_foreground(tmp_path: Path, landscape_video: Path):
    out = tmp_path / "short.mp4"
    extract_short(
        str(landscape_video), str(out), 0.0, 0.5,
        layout="fit-blur", foreground_zoom=1.6, background_blur=10,
        background_brightness=0.9,
    )
    assert out.exists()


def test_fit_blur_rejects_bad_background_brightness(landscape_video: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="background_brightness"):
        extract_short(
            str(landscape_video), str(tmp_path / "x.mp4"), 0.0, 0.5,
            layout="fit-blur", background_brightness=0,
        )


def test_fit_blur_end_past_eof_is_clamped(landscape_video: Path, tmp_path: Path):
    out = tmp_path / "short.mp4"
    extract_short(str(landscape_video), str(out), 1.0, 30.0, layout="fit-blur")

    _, _, duration = _probe(out)
    assert 1.8 <= duration <= 2.2


def test_end_past_eof_is_clamped(landscape_video: Path, tmp_path: Path):
    out = tmp_path / "short.mp4"
    extract_short(str(landscape_video), str(out), 1.0, 30.0)

    _, _, duration = _probe(out)
    assert 1.8 <= duration <= 2.2


def test_end_before_start_raises(landscape_video: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="must be after start"):
        extract_short(str(landscape_video), str(tmp_path / "x.mp4"), 2.0, 1.0)


def test_start_past_eof_raises(landscape_video: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="past the end"):
        extract_short(str(landscape_video), str(tmp_path / "x.mp4"), 5.0, 6.0)


def test_unknown_layout_raises(landscape_video: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown layout"):
        extract_short(str(landscape_video), str(tmp_path / "x.mp4"), 0.0, 1.0, layout="nope")


def test_crop_layout_rejects_narrower_than_nine_by_sixteen(tmp_path: Path):
    src = tmp_path / "tall.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "color=c=red:s=60x128:d=1:r=10",
            "-c:v", "libx264", str(src),
        ],
        capture_output=True, text=True, check=True,
    )

    with pytest.raises(ValueError, match="use layout 'stack'"):
        extract_short(str(src), str(tmp_path / "x.mp4"), 0.0, 0.5, layout="crop")


def test_cli_requires_exactly_one_range_option(landscape_video: Path, tmp_path: Path):
    runner = CliRunner()
    cmd = register({}).click_command

    both = runner.invoke(cmd, [str(landscape_video), "-s", "0", "-e", "1", "-d", "1"])
    assert both.exit_code == 2
    assert "exactly one of --end or --duration" in both.output

    neither = runner.invoke(cmd, [str(landscape_video), "-s", "0"])
    assert neither.exit_code == 2


def test_cli_rejects_crop_options_for_stack(landscape_video: Path, tmp_path: Path):
    runner = CliRunner()
    cmd = register({}).click_command

    result = runner.invoke(
        cmd, [str(landscape_video), "-s", "0", "-e", "1", "--zoom", "1.5"]
    )
    assert result.exit_code == 2
    assert "only apply" in result.output


def test_cli_rejects_fit_blur_options_for_crop(landscape_video: Path):
    runner = CliRunner()
    cmd = register({}).click_command

    result = runner.invoke(
        cmd, [str(landscape_video), "-s", "0", "-e", "1", "--layout", "crop", "--bg-blur", "10"]
    )
    assert result.exit_code == 2
    assert "--bg-blur" in result.output


def test_cli_rejects_bad_fit_blur_values(landscape_video: Path):
    runner = CliRunner()
    cmd = register({}).click_command

    result = runner.invoke(
        cmd, [str(landscape_video), "-s", "0", "-e", "1", "--layout", "fit-blur",
              "--bg-brightness", "0"]
    )
    assert result.exit_code == 2
    assert "bg-brightness" in result.output


def test_cli_writes_default_output(landscape_video: Path):
    runner = CliRunner()
    cmd = register({}).click_command

    result = runner.invoke(cmd, [str(landscape_video), "-s", "0", "-d", "1"])
    assert result.exit_code == 0, result.output
    expected = landscape_video.parent / "source_short.mp4"
    assert str(expected) in result.stdout
    assert expected.exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
