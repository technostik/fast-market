"""Regression tests: pool remove must work for error entries with missing files
and special-char filenames (apostrophes), plus frontend must not use inline
onclick interpolation for pool sources."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish import pool as sp_pool


def _isolate(monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_save_pool_to_disk", lambda: None)


def test_remove_error_entry_with_apostrophe_and_missing_file(monkeypatch):
    """Exact user scenario: French title with apostrophe, file deleted on disk."""
    _isolate(monkeypatch)
    src = "/home/joriel/Vidéos/Ils Se Moquaient de Musk, Google Prouve qu'il Avait Raison !.mp4"
    item = sp_pool.PoolItem(
        source=src,
        status="error",
        error_message="[source] Source file not found",
    )
    sp_pool._pool.append(item)
    assert not Path(src).exists()  # file really is missing
    assert sp_pool.remove_from_pool(src) is True
    assert sp_pool._pool == []


def test_remove_unknown_source_returns_false(monkeypatch):
    _isolate(monkeypatch)
    sp_pool._pool.append(sp_pool.PoolItem(source="/v/a.mp4", status="error"))
    assert sp_pool.remove_from_pool("/v/does-not-exist.mp4") is False
    assert len(sp_pool._pool) == 1


def test_remove_falls_back_to_basename(monkeypatch, tmp_path):
    """Stale entry whose parent dir moved must still be deletable."""
    _isolate(monkeypatch)
    stale = str(tmp_path / "old_dir" / "clip.mp4")
    sp_pool._pool.append(sp_pool.PoolItem(source=stale, status="error"))
    moved = str(tmp_path / "new_dir" / "clip.mp4")
    assert sp_pool.remove_from_pool(moved) is True
    assert sp_pool._pool == []


def test_frontend_pool_buttons_do_not_interpolate_source_in_onclick():
    html = (Path(__file__).parent.parent / "webux" / "short_publish" / "frontend.html").read_text(
        encoding="utf-8"
    )
    assert "onclick=\"pool" not in html, "pool buttons must not use inline onclick"
    assert "onclick='pool" not in html, "pool buttons must not use inline onclick"
    assert "onclick=\"previewFile" not in html, "preview buttons must not use inline onclick"
    assert "${item.source}" not in html, "raw source must not be interpolated into JS strings"
    assert "${f.path}" not in html or "data-preview" in html, "raw file path must not be interpolated into inline JS"
    assert "addEventListener" in html
