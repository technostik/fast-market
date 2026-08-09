from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import SyncResult
from core.pool_enrich import EnrichResult


class _FakeStore:
    def __init__(self, pool=None, docs=None):
        self.pool = pool or []
        self.docs = docs or []

    def get_pool_items(self, source=None, status=None):
        return [
            it
            for it in self.pool
            if (source is None or it["source_plugin"] == source)
            and (status is None or it["status"] == status)
        ]

    def list_documents_extended(self, source=None, filters=None, order_by="date",
                                reverse=False, limit=100):
        return self.docs


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
    monkeypatch.setattr(
        mod,
        "_sync_pool_worker",
        lambda store, engine, plugin, pool_items, vault_path=None: SyncResult(
            source="youtube", processed=1, indexed=1, skipped=0, failures=[]
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


# ── sync-pool: index selected not-synced items ────────────────────────────────


def test_sync_pool_indexes_selected_handles(client, monkeypatch):
    import webux.corpus_browser.register as mod

    store = _FakeStore(pool=[
        {"source_plugin": "youtube", "source_id": "v1", "status": "pending",
         "metadata": {"title": "One"}, "added_at": "2026-08-01T00:00:00", "synced_at": None},
        {"source_plugin": "youtube", "source_id": "v2", "status": "pending",
         "metadata": {"title": "Two"}, "added_at": "2026-08-01T00:00:00", "synced_at": None},
    ])
    backend = {"config": {}, "store": store, "engine": None,
               "plugins": {"youtube": object(), "obsidian": object()}}
    monkeypatch.setattr(mod, "_backend_factory", lambda: backend)

    resp = client.post("/api/corpus_browser/sync-pool",
                       json={"source": "youtube", "handles": ["pool:youtube:v1"]})
    assert resp.status_code == 200, resp.text
    job = client.get(f"/api/corpus_browser/sync-pool/status/{resp.json()['job_id']}").json()
    assert job["status"] == "done"
    assert job["result"]["indexed"] == 1


def test_sync_pool_requires_source_plugin(client):
    resp = client.post("/api/corpus_browser/sync-pool",
                       json={"source": "bogus", "handles": ["pool:bogus:x"]})
    assert resp.status_code == 400


def test_sync_pool_requires_handles(client):
    resp = client.post("/api/corpus_browser/sync-pool",
                       json={"source": "youtube", "handles": []})
    assert resp.status_code == 400


# ── browse: View all merges docs + pool rows ──────────────────────────────────


def test_browse_view_all_includes_pool_rows(client, monkeypatch):
    import webux.corpus_browser.register as mod

    store = _FakeStore(
        pool=[
            {"source_plugin": "youtube", "source_id": "v9", "status": "pending",
             "metadata": {"title": "Pool One"}, "added_at": "2026-08-01T00:00:00", "synced_at": None},
        ],
        docs=[
            {"handle": "yt-one", "source_plugin": "youtube", "source_id": "v1",
             "title": "Doc One", "raw_text": "...", "updated_at": "2026-08-01T00:00:00",
             "metadata": {}},
        ],
    )
    backend = {"config": {}, "store": store, "engine": None,
               "plugins": {"youtube": object(), "obsidian": object()}}
    monkeypatch.setattr(mod, "_backend_factory", lambda: backend)

    resp = client.get("/api/corpus_browser/browse?state=all")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2
    handles = [i["handle"] for i in data["items"]]
    assert "pool:youtube:v9" in handles
    assert "yt-one" in handles
