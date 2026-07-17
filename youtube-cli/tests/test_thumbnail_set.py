from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

from commands.thumbnail_set.register import _prepare_thumbnail, YT_W, YT_H, YT_MAX_BYTES


def _make(path: Path, w: int, h: int, color=(255, 0, 0)) -> str:
    Image.new("RGB", (w, h), color).save(path)
    return str(path)


def test_correct_size_passthrough(tmp_path):
    f = _make(tmp_path / "t.png", YT_W, YT_H)
    out, resized = _prepare_thumbnail(f)
    assert resized is False
    img = Image.open(out)
    assert img.size == (YT_W, YT_H)


def test_wrong_size_is_resized_and_padded(tmp_path):
    f = _make(tmp_path / "t.png", 800, 800)  # square -> letterboxed
    out, resized = _prepare_thumbnail(f)
    assert resized is True
    img = Image.open(out)
    assert img.size == (YT_W, YT_H)


def test_oversized_is_under_limit(tmp_path):
    # Build a fully-random image that won't compress and exceeds 2 MiB.
    import os

    big = Image.frombytes(
        "RGB", (YT_W, YT_H), os.urandom(YT_W * YT_H * 3)
    )
    f = tmp_path / "big.png"
    big.save(f)
    assert f.stat().st_size > YT_MAX_BYTES, "sanity: source should exceed limit"
    out, resized = _prepare_thumbnail(str(f))
    assert Path(out).stat().st_size <= YT_MAX_BYTES
