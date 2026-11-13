"""Pool retry: path matching, structured failures, and disk persistence.

Retry is the only way to restart a failed pipeline row, so a silent no-op is
a real bug: these tests pin the returned contract the frontend relies on.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from webux.short_publish import pool as pool_mod
from webux.short_publish.pool import PoolItem

# The fixture below stubs ``start_pool`` so retry tests do not need an event
# loop; the worker test needs the real implementation.
_REAL_START_POOL = pool_mod.start_pool


@pytest.fixture
def pool_env(tmp_path, monkeypatch):
    """Point the pool file at a temp dir and stop the worker from starting."""
    monkeypatch.setattr(
        pool_mod, "_load_publish_cfg", lambda *a, **k: {"video_source_path": str(tmp_path)}
    )
    monkeypatch.setattr(pool_mod, "start_pool", lambda: None)
    monkeypatch.setattr(pool_mod, "_pool", [])
    monkeypatch.setattr(pool_mod, "_pool_state", {"running": False, "current": None})
    monkeypatch.setattr(pool_mod, "_pool_auto_start", True)
    monkeypatch.setattr(pool_mod, "_worker_task", None)
    return tmp_path


def _make_source(tmp_path: Path, name: str = "clip.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"fake-video")
    # The failed-step marker lives in the sidecar meta log.
    meta = tmp_path / f"{path.stem}-meta.json"
    meta.write_text(
        json.dumps({"completed_steps": [0, 1], "skipped_steps": [], "profile": "test"}),
        encoding="utf-8",
    )
    return path


def _add_item(source: str, status: str = "error") -> PoolItem:
    item = PoolItem(source=source, profile="test", status=status)
    pool_mod._pool.append(item)
    return item


def test_retry_requeues_and_persists_from_step(pool_env):
    src = _make_source(pool_env)
    item = _add_item(str(src))

    result = pool_mod.retry_item(str(src))

    assert result["ok"] is True
    # Step 2 is the first unfinished step, and the first retry deliberately
    # rolls one step back, so 1 is where the pipeline resumes.
    assert result["from_step"] == 1
    assert item.status == "queued"
    assert item.retry_count == 1
    assert item.retry_from_step == 1

    saved = json.loads((pool_env / ".publish-pool.json").read_text(encoding="utf-8"))
    assert saved["items"][0]["retry_count"] == 1
    assert saved["items"][0]["retry_from_step"] == 1


def test_retry_from_step_survives_reload(pool_env):
    src = _make_source(pool_env)
    _add_item(str(src))
    pool_mod.retry_item(str(src))

    pool_mod._pool = []
    pool_mod._load_pool_from_disk()

    assert len(pool_mod._pool) == 1
    assert pool_mod._pool[0].retry_from_step == 1
    assert pool_mod._pool[0].retry_count == 1


def test_retry_matches_item_added_with_unresolved_path(pool_env, monkeypatch):
    src = _make_source(pool_env)
    # Simulate an old pool entry written from another cwd / through a symlink.
    _add_item(src.name)

    result = pool_mod.retry_item(str(src.resolve()))

    assert result["ok"] is True
    assert pool_mod._pool[0].status == "queued"


def test_retry_missing_source_reports_error(pool_env):
    src = _make_source(pool_env)
    _add_item(str(src))
    src.unlink()

    result = pool_mod.retry_item(str(src))

    assert result["ok"] is False
    assert "not found" in result["error"].lower()
    # The row must stay retryable (not flipped to queued and stuck).
    assert pool_mod._pool[0].status == "error"


def test_retry_unknown_item_reports_error(pool_env):
    result = pool_mod.retry_item(str(pool_env / "ghost.mp4"))

    assert result["ok"] is False
    assert "not found" in result["error"].lower()


@pytest.mark.parametrize("status", ["queued", "processing", "finished", "skipped"])
def test_retry_rejects_non_failed_items(pool_env, status):
    src = _make_source(pool_env)
    _add_item(str(src), status=status)

    result = pool_mod.retry_item(str(src))

    assert result["ok"] is False
    assert "not failed" in result["error"].lower()
    assert pool_mod._pool[0].status == status


def test_second_retry_rolls_back_one_more_step(pool_env):
    src = _make_source(pool_env)
    item = _add_item(str(src))

    first = pool_mod.retry_item(str(src))
    item.status = "error"
    second = pool_mod.retry_item(str(src))

    assert second["ok"] is True
    assert second["from_step"] == first["from_step"] - 1
    assert item.retry_count == 2


def test_start_pool_recreates_a_dead_worker(pool_env, monkeypatch):
    """``running=True`` must not hide a worker task that already finished."""

    async def worker():
        await asyncio.sleep(3600)

    async def scenario():
        monkeypatch.setattr(pool_mod, "_pool_worker", worker)

        # Flag set but no task (e.g. after a server restart): start it.
        pool_mod._pool_state["running"] = True
        pool_mod._worker_task = None
        _REAL_START_POOL()
        created = pool_mod._worker_task
        assert created is not None and not created.done()

        # A live worker is never duplicated.
        _REAL_START_POOL()
        assert pool_mod._worker_task is created

        # A finished task must be replaced even though running is still True,
        # otherwise a retried item would sit in the queue forever.
        created.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await created
        _REAL_START_POOL()
        replacement = pool_mod._worker_task
        assert replacement is not created and not replacement.done()

        replacement.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await replacement

    asyncio.run(scenario())
