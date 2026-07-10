"""Tests for Short Publish stop / interrupt logic (sync parts)."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish.models import Job, Step
from webux.short_publish import pipeline, state, pool


def make_job():
    return Job(
        job_id="test",
        source="/tmp/test.mp4",
        prompt_title="t",
        prompt_summary="s",
        do_remove_silence=True,
        do_burn_subtitles=True,
        language="fr",
        model="medium",
        privacy="unlisted",
        transcript_mode="normal",
        steps=[Step("Remove silence"), Step("Extract transcript")],
    )


def test_finish_step_success_keeps_going():
    job = make_job()
    step = job.steps[0]
    assert pipeline._finish_step(job, step, 0) is False
    assert step.status == "pending"  # unchanged on success


def test_finish_step_error_aborts():
    job = make_job()
    step = job.steps[0]
    assert pipeline._finish_step(job, step, 1) is True
    assert step.status == "error"
    assert job.status == "error"


def test_finish_step_stop_takes_precedence_over_error():
    job = make_job()
    job.stop_requested = True
    step = job.steps[0]
    # rc != 0 but a stop was requested -> reported as stopped, not error
    assert pipeline._finish_step(job, step, 1) is True
    assert step.status == "skipped"
    assert "Stopped" in (step.output or "")
    assert job.status == "stopped"


def test_abort_if_stopped_finalizes():
    job = make_job()
    job.stop_requested = True
    step = job.steps[1]
    assert pipeline._abort_if_stopped(job, step) is True
    assert step.status == "skipped"
    assert job.status == "stopped"


def test_abort_if_stopped_passthrough_when_running():
    job = make_job()
    step = job.steps[1]
    assert pipeline._abort_if_stopped(job, step) is False


def test_request_stop_terminates_active_subprocess():
    # Spawn a harmless process that ignores SIGTERM by default terminating.
    async def _run():
        proc = await asyncio.create_subprocess_exec(
            "sleep", "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        state.set_active_proc(proc)
        job = make_job()
        state.set_active_job(job)
        try:
            state.request_stop()
            # Give the signal a moment to be delivered.
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            return proc.returncode, job.stop_requested
        finally:
            state.clear_active_proc()
            state.clear_active_job()

    rc, stop_flag = asyncio.run(_run())
    # SIGTERM -> negative return code (terminated by signal)
    assert rc is not None and rc < 0
    assert stop_flag is True


def test_stop_pool_clears_auto_start_and_running():
    # Stop must fully halt the pool and prevent status-poll auto-restart.
    pool._pool_auto_start = True
    pool._pool_state["running"] = True
    pool.stop_pool()
    assert pool._pool_state["running"] is False
    assert pool._pool_auto_start is False
    # After stop, a status read must NOT auto-restart the worker.
    assert not (not pool._pool_state["running"] and pool._pool_auto_start)


def test_redo_unfinished_requeues_all_and_starts(monkeypatch):
    items = [
        pool.PoolItem(source="/tmp/a.mp4", status="finished"),
        pool.PoolItem(source="/tmp/b.mp4", status="error"),
        pool.PoolItem(source="/tmp/c.mp4", status="stopped"),
        pool.PoolItem(source="/tmp/d.mp4", status="queued"),
        pool.PoolItem(source="/tmp/e.mp4", status="skipped"),
    ]
    # Isolate from the real pool state AND prevent any disk writes so the test
    # can never corrupt the user's actual .publish-pool.json.
    monkeypatch.setattr(pool, "_pool", items)
    monkeypatch.setattr(pool, "_save_pool_to_disk", lambda: None)
    monkeypatch.setattr(pool, "_update_meta_status", lambda *a, **k: None)
    started = {}
    monkeypatch.setattr(pool, "start_pool", lambda: started.setdefault("yes", True))

    pool.redo_unfinished()

    # finished is left alone; every unfinished item is requeued
    assert items[0].status == "finished"
    for it in items[1:]:
        assert it.status == "queued"
    assert started.get("yes") is True


