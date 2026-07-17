from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import webux.long_publish.register as reg


@pytest.fixture
def store():
    data = {}
    reg._load_publish_cfg = lambda: dict(data)
    reg._save_publish_cfg = lambda pub: data.update(pub)
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
    # base renamed to <stem>_thumb<ext>
    assert body["base"].endswith("_thumb.png")
