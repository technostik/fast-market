"""Tests for source-video filtering, no_signature_* guards and pool requeue."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish import pool as sp_pool
from webux.short_publish.models import is_no_signature_source, Job, Step


# ── is_no_signature_source ────────────────────────────────────────────────

def test_no_signature_prefix_detected():
    assert is_no_signature_source("/home/v/no_signature_My Title.mp4")
    assert is_no_signature_source("/home/v/no_signature_abc.mkv")


def test_normal_source_not_detected():
    assert not is_no_signature_source("/home/v/original.mp4")
    assert not is_no_signature_source("/home/v/stuff_no_signature.mp4")
    assert not is_no_signature_source("/home/v/MyNo_signature_at_start.mp4")


# ── add_to_pool guard ─────────────────────────────────────────────────────

def test_add_to_pool_rejects_no_signature_source(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    monkeypatch.setattr(sp_pool, "_save_pool_to_disk", lambda: None)
    monkeypatch.setattr(sp_pool, "start_pool", lambda: None)
    ok = sp_pool.add_to_pool(str(tmp_path / "no_signature_x.mp4"))
    assert ok is False
    assert sp_pool._pool == []


def test_add_to_pool_accepts_normal_source(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    monkeypatch.setattr(sp_pool, "_save_pool_to_disk", lambda: None)
    monkeypatch.setattr(sp_pool, "start_pool", lambda: None)
    monkeypatch.setattr(sp_pool, "_get_video_duration_cli_sync", lambda p: 10.0)
    src = tmp_path / "clips"
    src.mkdir()
    video = src / "orig.mp4"
    video.write_text("x")
    ok = sp_pool.add_to_pool(str(video))
    assert ok is True


# ── remove_from_pool requeue reset ───────────────────────────────────────

def test_remove_from_pool_resets_finished_meta(tmp_path, monkeypatch):
    src = tmp_path / "clips"
    src.mkdir()
    video = src / "orig.mp4"
    video.write_text("x")
    meta_path = src / "orig-meta.json"
    meta_path.write_text(json.dumps({
        "source": str(video),
        "status": "finished",
        "completed_steps": [0, 1, 2, 3, 4, 5, 6],
        "skipped_steps": [],
        "finished_at": 1234567890.0,
    }))

    monkeypatch.setattr(sp_pool, "_pool", [sp_pool.PoolItem(source=str(video), status="finished")])
    monkeypatch.setattr(sp_pool, "_save_pool_to_disk", lambda: None)

    removed = sp_pool.remove_from_pool(str(video))
    assert removed is True
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == "queued"
    assert "completed_steps" not in meta
    assert "skipped_steps" not in meta
    assert "finished_at" not in meta


# ── upload_duration_seconds exposed in job dict ───────────────────────────

def test_job_to_dict_exposes_upload_duration():
    job = Job(
        job_id="j1",
        source="/v/a.mp4",
        prompt_title="t", prompt_summary="s",
        do_remove_silence=True, do_burn_subtitles=True,
        language="fr", model="medium", privacy="unlisted",
        steps=[Step(name="x") for _ in range(7)],
        upload_duration_seconds=123.4,
    )
    assert job.to_dict()["upload_duration_seconds"] == 123.4


def test_job_to_dict_upload_duration_none_by_default():
    job = Job(
        job_id="j2",
        source="/v/a.mp4",
        prompt_title="t", prompt_summary="s",
        do_remove_silence=True, do_burn_subtitles=True,
        language="fr", model="medium", privacy="unlisted",
        steps=[Step(name="x") for _ in range(7)],
    )
    assert job.to_dict()["upload_duration_seconds"] is None


# ── pool load drops no_signature sources ─────────────────────────────────

def test_load_pool_drops_no_signature_source(tmp_path, monkeypatch):
    src = tmp_path / "clips"
    src.mkdir()
    pool_file = src / ".publish-pool.json"
    pool_file.write_text(json.dumps({"items": [
        {"source": str(src / "no_signature_Bad.mp4"), "status": "error"},
        {"source": str(src / "orig.mp4"), "status": "queued"},
    ]}))
    monkeypatch.setattr(sp_pool, "_pool_file", lambda: pool_file)
    monkeypatch.setattr(sp_pool, "_load_meta", lambda s: {})
    sp_pool._load_pool_from_disk()
    sources = [it.source for it in sp_pool._pool]
    assert str(src / "orig.mp4") in sources
    assert not any("no_signature_" in Path(s).name for s in sources)


# ── pool state exposes persisted upload duration ──────────────────────────

def test_pool_state_exposes_upload_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    item = sp_pool.PoolItem(source=str(tmp_path / "a.mp4"), status="finished",
                            duration_seconds=200.0, upload_duration_seconds=152.0)
    sp_pool._pool.append(item)
    state = sp_pool.get_pool_state()
    assert state["items"][0]["upload_duration_seconds"] == 152.0


def test_pool_state_upload_duration_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    item = sp_pool.PoolItem(source=str(tmp_path / "b.mp4"), status="queued")
    sp_pool._pool.append(item)
    state = sp_pool.get_pool_state()
    assert state["items"][0]["upload_duration_seconds"] is None

