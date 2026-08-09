from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pool_enrich import EnrichResult


class _FakeStore:
    def get_pool_items(self, source=None, status=None):
        return []


@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import webux.corpus_browser.register as mod

    backend = {
        "config": {},
        "store": _FakeStore(),
        "engine": None,
        "plugins": {"youtube": object(), "obsidian": object()},
    }
    monkeypatch.setattr(mod, "_backend_factory", lambda: backend)
    monkeypatch.setattr(
        mod,
        "_enrich_worker",
        lambda store, source, **kw: EnrichResult(
            source=source, processed=2, enriched=2, skipped=0
        ),
    )

    app = FastAPI()
    app.include_router(mod.router, prefix="/api/corpus_browser")
    return TestClient(app)


def test_enrich_default_source(client):
    resp = client.post("/api/corpus_browser/enrich", json={})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "running"
    assert data["source"] == "youtube"

    status = client.get(f"/api/corpus_browser/enrich/status/{data['job_id']}")
    assert status.status_code == 200
    job = status.json()
    assert job["status"] == "done"
    assert job["result"]["source"] == "youtube"
    assert job["result"]["enriched"] == 2


def test_enrich_explicit_source(client):
    resp = client.post("/api/corpus_browser/enrich", json={"source": "obsidian"})
    assert resp.status_code == 200
    assert resp.json()["source"] == "obsidian"


def test_enrich_unknown_source_400(client):
    resp = client.post("/api/corpus_browser/enrich", json={"source": "bogus"})
    assert resp.status_code == 400
    assert "bogus" in resp.json()["detail"]


def test_enrich_status_unknown_job_404(client):
    resp = client.get("/api/corpus_browser/enrich/status/nope")
    assert resp.status_code == 404
