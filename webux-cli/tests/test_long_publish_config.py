from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import webux.long_publish.register as reg
import webux.long_publish.utils as pub_utils
from common.core.config import ConfigError
from webux.long_publish.models import DEFAULT_VIDEO_EXTENSIONS


@pytest.fixture
def store(monkeypatch):
    data = {}
    monkeypatch.setattr(reg, "_load_publish_cfg", lambda: dict(data))
    monkeypatch.setattr(reg, "_save_publish_cfg", lambda pub: data.update(pub))
    # GET /config migrates the real youtube config. Keep this fixture off disk.
    monkeypatch.setattr(reg, "_migrate_publish_cfg_if_needed", lambda: False)
    return data


def _cfg_payload(**over):
    base = dict(
        video_source_path="/x", video_extensions="mp4", signature="",
        signature_video_path="", default_title_prompt="", default_description_prompt="",
        default_thumbnail_prompt="", default_thumbnail_overlay_prompt="",
        thumbnail_engine="", thumbnail_overlay_fg="", thumbnail_overlay_bg="",
        thumbnail_overlay_size_pct=0, thumbnail_overlay_offset=0,
        modal_usage_url="", transcript_mode="normal",
        transcript_model="medium", transcript_language="fr",
    )
    base.update(over)
    return base


def test_config_roundtrip_overlay_defaults(store):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(reg.router)
    from fastapi import FastAPI
    app = FastAPI(); app.include_router(reg.router)
    with TestClient(app) as client:
        r = client.post("/config", json=_cfg_payload(
            thumbnail_overlay_size_pct=120, thumbnail_overlay_offset=10))
        assert r.status_code == 200
        assert store["thumbnail_overlay_size_pct"] == 120
        assert store["thumbnail_overlay_offset"] == 10
        cfg = client.get("/config").json()
    assert cfg["thumbnail_overlay_size_pct"] == 120
    assert cfg["thumbnail_overlay_offset"] == 10


def test_resolve_overlay_defaults_falls_back_to_config(store):
    store["thumbnail_overlay_size_pct"] = 130
    store["thumbnail_overlay_offset"] = 15
    fg, bg, effect, size_pct, offset = reg._resolve_overlay_defaults({}, store)
    assert size_pct == 130
    assert offset == 15


def _make_source(tmp_path: Path, overlay_title: str = "") -> str:
    src = tmp_path / "vid.mp4"
    src.write_text("x")
    meta = {"files": {}, "thumbnail_overlay_title": overlay_title}
    (tmp_path / "vid-long-meta.json").write_text(json.dumps(meta))
    return str(src)


def test_replace_base_image(tmp_path, store, monkeypatch):
    monkeypatch.setattr(reg, "_image", lambda: "image")
    monkeypatch.setattr(reg, "_resolve_overlay_defaults",
                        lambda meta, cfg: ("", "", "", 0, 0))
    monkeypatch.setattr(reg, "_append_overlay_opts", lambda *a, **k: [])

    from PIL import Image
    img = tmp_path / "in.png"
    Image.new("RGB", (10, 10), (255, 0, 0)).save(img)

    src = _make_source(tmp_path, overlay_title="")
    from fastapi import FastAPI
    app = FastAPI(); app.include_router(reg.router)
    with TestClient(app) as client:
        r = client.post("/replace-base-image",
                        data={"source": src, "base_image": str(img)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert Path(body["base"]).exists()
    # base renamed to <stem>_thumb_<N><ext>
    assert body["base"].endswith("_thumb_1.png")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("mp4,mkv", True),
        ("mkv, mp4", True),
        ("MP4,MKV", True),
        ("mp4,mkv,webm", False),
        ("mp4", False),
        ("mp4,mkv,mov", False),
        ("", False),
    ],
)
def test_needs_webm_migration(raw, expected):
    assert pub_utils._needs_webm_migration(raw) is expected


def test_needs_webm_migration_rejects_non_string():
    with pytest.raises(ConfigError):
        pub_utils._needs_webm_migration(["mp4", "mkv"])


def _patch_publish_cfg(monkeypatch, publish: dict) -> dict:
    state = {"youtube": {"publish": dict(publish)}}

    def load(_name):
        return {"youtube": {"publish": dict(state["youtube"]["publish"])}}

    def save(pub):
        state["youtube"]["publish"] = dict(pub)

    monkeypatch.setattr(pub_utils, "load_tool_config", load)
    monkeypatch.setattr(pub_utils, "_save_publish_cfg", save)
    return state


def test_migrate_legacy_extensions_persists_webm(monkeypatch):
    state = _patch_publish_cfg(monkeypatch, {"video_extensions": "mp4,mkv", "signature": "keep"})
    assert pub_utils._migrate_publish_cfg_if_needed() is True
    assert state["youtube"]["publish"]["video_extensions"] == DEFAULT_VIDEO_EXTENSIONS
    assert state["youtube"]["publish"]["signature"] == "keep"
    assert pub_utils._migrate_publish_cfg_if_needed() is False


def test_migrate_leaves_custom_extension_list(monkeypatch):
    state = _patch_publish_cfg(monkeypatch, {"video_extensions": "mp4"})
    assert pub_utils._migrate_publish_cfg_if_needed() is False
    assert state["youtube"]["publish"]["video_extensions"] == "mp4"


def test_migrate_raises_when_publish_is_not_a_mapping(monkeypatch):
    monkeypatch.setattr(
        pub_utils, "load_tool_config", lambda _name: {"youtube": {"publish": "mp4,mkv"}}
    )
    with pytest.raises(ConfigError):
        pub_utils._migrate_publish_cfg_if_needed()


def test_get_config_returns_migrated_extensions(monkeypatch):
    state = _patch_publish_cfg(monkeypatch, {"video_extensions": "mkv,mp4", "signature": "s"})
    monkeypatch.setattr(reg, "_migrate_publish_cfg_if_needed", pub_utils._migrate_publish_cfg_if_needed)
    monkeypatch.setattr(reg, "_load_publish_cfg", pub_utils._load_publish_cfg)
    monkeypatch.setattr(reg, "_save_publish_cfg", pub_utils._save_publish_cfg)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(reg.router)
    with TestClient(app) as client:
        cfg = client.get("/config").json()
    assert cfg["video_extensions"] == DEFAULT_VIDEO_EXTENSIONS
    assert state["youtube"]["publish"]["video_extensions"] == DEFAULT_VIDEO_EXTENSIONS
    assert cfg["signature"] == "s"


def test_list_videos_includes_webm_by_default(tmp_path):
    (tmp_path / "clip.webm").write_bytes(b"x")
    (tmp_path / "clip.mp4").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("no")
    (tmp_path / "clip_nosilence.webm").write_bytes(b"x")

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(reg.router)
    with TestClient(app) as client:
        listed = client.get("/list-videos", params={"path": str(tmp_path)})
        omitted = client.get(
            "/list-videos",
            params={"path": str(tmp_path), "extensions": "mp4,mkv"},
        )
    assert listed.status_code == 200
    assert {v["name"] for v in listed.json()["videos"]} == {"clip.webm", "clip.mp4"}
    assert {v["name"] for v in omitted.json()["videos"]} == {"clip.mp4"}


def _write_meta(tmp_path: Path, stem: str, completed: list[int], skipped: list[int]):
    src = tmp_path / f"{stem}.webm"
    src.write_bytes(b"x")
    meta = {
        "source": str(src),
        "completed_steps": completed,
        "skipped_steps": skipped,
        "files": {},
    }
    (tmp_path / f"{stem}-long-meta.json").write_text(json.dumps(meta))
    return src


def test_list_videos_keeps_source_when_upload_was_skipped(tmp_path):
    """A run that finished processing but skipped the tail steps (no upload)
    must stay selectable — it was never published."""
    _write_meta(tmp_path, "clip", [0, 1, 2], [3, 4, 5])

    from fastapi import FastAPI
    app = FastAPI(); app.include_router(reg.router)
    with TestClient(app) as client:
        listed = client.get("/list-videos", params={"path": str(tmp_path)})
    assert listed.status_code == 200
    videos = {v["name"]: v for v in listed.json()["videos"]}
    assert "clip.webm" in videos
    assert videos["clip.webm"]["resumable"] is True


def test_list_videos_hides_fully_uploaded_source(tmp_path):
    """A run with every step completed (upload done) stays hidden."""
    _write_meta(tmp_path, "clip", [0, 1, 2, 3, 4, 5], [])

    from fastapi import FastAPI
    app = FastAPI(); app.include_router(reg.router)
    with TestClient(app) as client:
        listed = client.get("/list-videos", params={"path": str(tmp_path)})
    assert listed.status_code == 200
    assert {v["name"] for v in listed.json()["videos"]} == set()
