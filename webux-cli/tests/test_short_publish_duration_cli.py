"""Tests for duration display support: `video duration` CLI helper and pool
duration_seconds exposure."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish import utils as sp_utils
from webux.short_publish import pool as sp_pool


def _reset_cache():
    sp_utils._duration_cache.clear()


def _fake_run(seconds: float):
    def fake(cmd, **kwargs):
        class R:
            stdout = f"{seconds}\n"
            stderr = ""
            returncode = 0
        return R()
    return fake


def test_duration_cli_helper_parses_output(tmp_path):
    _reset_cache()
    video = tmp_path / "clip.mp4"
    video.write_text("x")
    with patch.object(sp_utils.subprocess, "run", side_effect=_fake_run(83.0)):
        assert sp_utils._get_video_duration_cli_sync(str(video)) == 83.0


def test_duration_cli_helper_caches_by_mtime(tmp_path):
    _reset_cache()
    video = tmp_path / "clip.mp4"
    video.write_text("x")
    with patch.object(sp_utils.subprocess, "run", side_effect=_fake_run(10.0)) as run_mock:
        assert sp_utils._get_video_duration_cli_sync(str(video)) == 10.0
        assert sp_utils._get_video_duration_cli_sync(str(video)) == 10.0
        assert run_mock.call_count == 1
    # Touching the file invalidates the cache
    video.write_text("y")
    with patch.object(sp_utils.subprocess, "run", side_effect=_fake_run(20.0)) as run_mock:
        assert sp_utils._get_video_duration_cli_sync(str(video)) == 20.0
        assert run_mock.call_count == 1


def test_duration_cli_helper_returns_zero_on_bad_output(tmp_path):
    _reset_cache()
    video = tmp_path / "clip.mp4"
    video.write_text("x")

    def bad_run(cmd, **kwargs):
        class R:
            stdout = "not-a-number\n"
            stderr = "boom"
            returncode = 1
        return R()

    with patch.object(sp_utils.subprocess, "run", side_effect=bad_run):
        assert sp_utils._get_video_duration_cli_sync(str(video)) == 0.0


def test_pool_state_includes_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    item = sp_pool.PoolItem(source=str(tmp_path / "a.mp4"), status="finished",
                            duration_seconds=42.0)
    sp_pool._pool.append(item)
    state = sp_pool.get_pool_state()
    assert state["items"][0]["duration_seconds"] == 42.0


def test_pool_state_lazy_computes_missing_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    item = sp_pool.PoolItem(source=str(tmp_path / "b.mp4"), status="queued")
    sp_pool._pool.append(item)
    with patch.object(sp_pool, "_get_video_duration_cli_sync", return_value=77.5):
        state = sp_pool.get_pool_state()
    assert state["items"][0]["duration_seconds"] == 77.5


def test_set_item_upload_duration_stores_processed_length(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    monkeypatch.setattr(sp_pool, "_save_pool_to_disk", lambda: None)
    src = tmp_path / "clip.mp4"
    src.write_text("x")
    item = sp_pool.PoolItem(source=str(src.resolve()), status="processing",
                            duration_seconds=999.0)
    sp_pool._pool.append(item)
    sp_pool.set_item_upload_duration(str(src), 41.0)
    assert item.upload_duration_seconds == 41.0
    state = sp_pool.get_pool_state()
    assert state["items"][0]["upload_duration_seconds"] == 41.0
    # Source length stays on duration_seconds; the processed length is separate.
    assert state["items"][0]["duration_seconds"] == 999.0


def test_pool_state_prefers_live_job_processed_duration(tmp_path, monkeypatch):
    # Import register first: its module import reloads the pool from disk.
    import webux.short_publish.register as sp_register
    from webux.short_publish.models import Job, Step, STEP_NAMES

    monkeypatch.setattr(sp_pool, "_pool", [])
    monkeypatch.setattr(sp_pool, "_pool_auto_start", False)
    src = str((tmp_path / "clip.mp4").resolve())
    item = sp_pool.PoolItem(source=src, status="processing", job_id="j1",
                            duration_seconds=999.0)
    sp_pool._pool.append(item)

    job = Job(
        job_id="j1", source=src, prompt_title="t", prompt_summary="s",
        do_remove_silence=True, do_burn_subtitles=True, language="fr",
        model="medium", privacy="unlisted",
        steps=[Step(name=n) for n in STEP_NAMES],
        upload_duration_seconds=55.0,
    )
    sp_register._jobs["j1"] = job
    state = sp_pool.get_pool_state()
    assert state["items"][0]["upload_duration_seconds"] == 55.0
    assert state["items"][0]["job"]["upload_duration_seconds"] == 55.0


def test_save_meta_persists_processed_duration(tmp_path, monkeypatch):
    from webux.short_publish.models import Job, Step, STEP_NAMES
    from webux.short_publish import utils as sp_utils

    src = tmp_path / "clip.mp4"
    src.write_text("x")
    job = Job(
        job_id="j1", source=str(src), prompt_title="t", prompt_summary="s",
        do_remove_silence=True, do_burn_subtitles=True, language="fr",
        model="medium", privacy="unlisted",
        steps=[Step(name=n) for n in STEP_NAMES],
        upload_duration_seconds=88.0,
    )
    sp_utils._save_meta(job)
    meta = sp_utils._load_meta(str(src))
    assert meta["upload_duration_seconds"] == 88.0


def test_record_processed_duration_probes_given_path_not_source(tmp_path, monkeypatch):
    import asyncio
    from webux.short_publish.models import Job, Step, STEP_NAMES
    from webux.short_publish import pipeline as sp_pipeline

    src = tmp_path / "source.mp4"
    processed = tmp_path / "Renamed Title.mp4"
    src.write_text("x")
    processed.write_text("y")
    job = Job(
        job_id="j1", source=str(src), prompt_title="t", prompt_summary="s",
        do_remove_silence=True, do_burn_subtitles=True, language="fr",
        model="medium", privacy="unlisted",
        steps=[Step(name=n) for n in STEP_NAMES],
    )
    probed = []

    async def fake_cli(path):
        probed.append(path)
        return 63.0

    monkeypatch.setattr(sp_pipeline, "_get_video_duration_cli", fake_cli)
    monkeypatch.setattr(sp_pipeline, "set_item_upload_duration", lambda *a, **k: None)
    seconds = asyncio.run(sp_pipeline._record_processed_duration(job, str(processed)))
    assert seconds == 63.0
    assert job.upload_duration_seconds == 63.0
    assert probed == [str(processed)]
