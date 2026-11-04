"""Per-plugin `busy_check` probes used by `GET /api/system/busy`."""

from __future__ import annotations

from types import SimpleNamespace

import webux.charisma.register as charisma_reg
import webux.short_publish.register as short_reg


def _job(status: str):
    return SimpleNamespace(status=status)


def test_short_publish_busy_when_pool_runs(monkeypatch):
    monkeypatch.setattr(short_reg, "_jobs", {})
    monkeypatch.setattr(short_reg, "pool_is_busy", lambda: True)
    assert short_reg._is_busy() is True


def test_short_publish_busy_when_immediate_job_runs(monkeypatch):
    monkeypatch.setattr(short_reg, "pool_is_busy", lambda: False)
    monkeypatch.setattr(short_reg, "_jobs", {"j1": _job("running")})
    assert short_reg._is_busy() is True


def test_short_publish_idle_when_jobs_are_terminal(monkeypatch):
    monkeypatch.setattr(short_reg, "pool_is_busy", lambda: False)
    monkeypatch.setattr(
        short_reg,
        "_jobs",
        {"a": _job("done"), "b": _job("error"), "c": _job("stopped")},
    )
    assert short_reg._is_busy() is False


def test_charisma_busy_while_a_scan_job_runs(monkeypatch):
    monkeypatch.setattr(charisma_reg, "_jobs", {"a": _job("running")})
    assert charisma_reg._is_busy() is True


def test_charisma_idle_when_scans_are_done(monkeypatch):
    monkeypatch.setattr(charisma_reg, "_jobs", {"a": _job("done")})
    assert charisma_reg._is_busy() is False
