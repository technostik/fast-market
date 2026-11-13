"""Placement tests for `video burn-subtitles` (ASS Alignment override)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.burn_subtitles.register import (
    POSITIONS,
    _apply_position,
    _force_style,
    burn_ass_subtitles,
)

WIDTH, HEIGHT = 320, 568


def _make_dark_video(path: Path, duration: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x202020:s={WIDTH}x{HEIGHT}:d={duration}:r=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _write_ass(path: Path) -> None:
    path.write_text(
        f"""[Script Info]
Title: placement test
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,TEST
""",
        encoding="utf-8",
    )


def _bright_text_bbox(video: Path, tmp_path: Path) -> tuple[int, int, int, int]:
    """Bounding box of the near-white subtitle glyphs in the middle frame."""
    from PIL import Image

    frame_png = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(video),
         "-frames:v", "1", str(frame_png)],
        check=True,
    )
    image = Image.open(frame_png).convert("RGB")
    pixels = image.load()
    xs, ys = [], []
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue = pixels[x, y]
            if red > 200 and green > 200 and blue > 200:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise AssertionError("no subtitle pixels found")
    return min(xs), min(ys), max(xs), max(ys)


def test_force_style_does_not_set_alignment():
    # force_style Alignment is mirrored by this ffmpeg/libass build, so
    # placement must not depend on it.
    style = _force_style(96)
    assert "Alignment" not in style
    assert "Fontsize=96" in style


def test_apply_position_rewrites_style_alignment():
    source = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, Alignment, MarginL\n"
        "Style: Default,Arial,96,&H00FFFFFF,2,0\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello\n"
    )

    rewritten = _apply_position(source, "bottom")

    assert "Style: Default,Arial,96,&H00FFFFFF,2,0" in rewritten
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello" in rewritten

    top = _apply_position(source, "top")
    assert "Style: Default,Arial,96,&H00FFFFFF,8,0" in top


def test_apply_position_rejects_ass_without_alignment_column():
    with pytest.raises(ValueError, match="no style Format line"):
        _apply_position("Style: Default,Arial,96\nDialogue: 0,0,Default,,Hi", "top")


def test_apply_position_rejects_unknown_position():
    source = "Format: Name, Alignment\nStyle: Default,2\n"
    with pytest.raises(ValueError, match="Unknown subtitle position"):
        _apply_position(source, "sideways")


@pytest.mark.parametrize(
    "position,expect",
    [
        ("top-left", lambda x1, y1, x2, y2: y2 < 0.3 * HEIGHT and x1 < 0.3 * WIDTH),
        ("top", lambda x1, y1, x2, y2: y2 < 0.3 * HEIGHT and abs((x1 + x2) / 2 - WIDTH / 2) < 0.1 * WIDTH),
        ("middle", lambda x1, y1, x2, y2: 0.35 * HEIGHT < (y1 + y2) / 2 < 0.65 * HEIGHT),
        ("bottom", lambda x1, y1, x2, y2: y1 > 0.7 * HEIGHT and abs((x1 + x2) / 2 - WIDTH / 2) < 0.1 * WIDTH),
    ],
)
def test_position_places_text(position: str, expect, tmp_path: Path):
    video = tmp_path / "in.mp4"
    ass = tmp_path / "subs.ass"
    out = tmp_path / "out.mp4"
    _make_dark_video(video)
    _write_ass(ass)

    burn_ass_subtitles(str(video), str(ass), str(out), subtitle_size=40, position=position)

    bbox = _bright_text_bbox(out, tmp_path)
    assert expect(*bbox), f"position {position!r} bbox={bbox}"


def test_cli_exposes_position_and_rejects_unknown(tmp_path: Path):
    from click.testing import CliRunner

    from commands.burn_subtitles.register import register

    video = tmp_path / "in.mp4"
    ass = tmp_path / "subs.ass"
    _make_dark_video(video)
    _write_ass(ass)

    runner = CliRunner()
    cmd = register({}).click_command

    help_result = runner.invoke(cmd, ["--help"])
    assert help_result.exit_code == 0
    assert "--position" in help_result.stdout
    assert "top-left" in help_result.stdout

    bad = runner.invoke(
        cmd, [str(video), str(ass), "--position", "sideways"]
    )
    assert bad.exit_code == 2

    good = runner.invoke(
        cmd, [str(video), str(ass), "--position", "bottom", "-o", str(tmp_path / "out.mp4")]
    )
    assert good.exit_code == 0, good.output
    assert (tmp_path / "out.mp4").exists()
