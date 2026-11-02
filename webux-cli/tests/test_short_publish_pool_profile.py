"""Regression tests: pool items must expose the profile (YouTube account) they
were added with, so the pipeline's "Edit in Studio" link can show it on hover."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish import pool as sp_pool


def _isolate(monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_save_pool_to_disk", lambda: None)
    monkeypatch.setattr(sp_pool, "start_pool", lambda: None)
    monkeypatch.setattr(sp_pool, "_get_video_duration_cli_sync", lambda path: 10.0)


def test_pool_state_exposes_profile(monkeypatch):
    _isolate(monkeypatch)
    sp_pool._pool.append(
        sp_pool.PoolItem(
            source="/videos/clip.mp4",
            profile="techno_sophia",
            status="finished",
            duration_seconds=10.0,
            studio_url="https://studio.youtube.com/video/abc/edit",
        )
    )
    state = sp_pool.get_pool_state()
    assert state["items"][0]["profile"] == "techno_sophia"


def test_add_to_pool_persists_profile(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    src = tmp_path / "clip.mp4"
    src.write_text("", encoding="utf-8")
    assert sp_pool.add_to_pool(str(src), profile="techno_sophia") is True
    state = sp_pool.get_pool_state()
    assert state["items"][0]["profile"] == "techno_sophia"


def test_pool_state_profile_falls_back_to_meta(monkeypatch, tmp_path):
    """Entries created before multi-profile support only have the profile in
    their *-meta.json log."""
    _isolate(monkeypatch)
    src = tmp_path / "clip.mp4"
    src.write_text("", encoding="utf-8")
    (tmp_path / "clip-meta.json").write_text(
        json.dumps({"profile": "joriel"}), encoding="utf-8"
    )
    sp_pool._pool.append(
        sp_pool.PoolItem(
            source=str(src),
            profile="",
            status="finished",
            duration_seconds=10.0,
        )
    )
    state = sp_pool.get_pool_state()
    assert state["items"][0]["profile"] == "joriel"


def test_pool_studio_link_shows_profile_tooltip():
    html = (
        Path(__file__).parent.parent / "webux" / "short_publish" / "frontend.html"
    ).read_text(encoding="utf-8")
    assert "Published with profile:" in html
    assert "item.profile" in html
    assert 'title="${profileTip' in html
