"""Multi-profile support: the `profile` column, filtering, and the browser API.

The column is written on every document / pool insert (explicit value, else the
active profile) and read back for the corpus browser profile filter. The Alembic
migration (0006) backfills pre-existing rows to "joriel"; that path is exercised
by opening a real file DB, not by these unit tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import Document
from core.pool_rows import pool_row
from storage.sqlalchemy_store import SearchFilters, SQLAlchemyStore


def _doc(source_id: str, profile: str) -> Document:
    return Document(
        source_plugin="youtube",
        source_id=source_id,
        title=f"Title {source_id}",
        raw_text="transcript body",
        handle=f"yt-{source_id}",
        profile=profile,
    )


def test_upsert_document_stores_profile():
    store = SQLAlchemyStore(":memory:")
    store.upsert_document(_doc("v1", "joriel"), "h1")
    assert store.get_document("youtube", "v1")["profile"] == "joriel"
    assert store.list_profiles() == ["joriel"]


def test_upsert_document_defaults_to_active_profile(monkeypatch):
    monkeypatch.setenv("FASTMARKET_PROFILE", "technostik")
    store = SQLAlchemyStore(":memory:")
    store.upsert_document(_doc("v1", ""), "h1")
    assert store.get_document("youtube", "v1")["profile"] == "technostik"


def test_list_profiles_unions_documents_and_pool():
    store = SQLAlchemyStore(":memory:")
    store.upsert_document(_doc("v1", "joriel"), "h1")
    store.upsert_pool_item("youtube", "p1", "pending", {}, profile="technostik")
    assert store.list_profiles() == ["joriel", "technostik"]


def test_document_profile_filter():
    store = SQLAlchemyStore(":memory:")
    store.upsert_document(_doc("v1", "joriel"), "h1")
    store.upsert_document(_doc("v2", "technostik"), "h2")
    joriel = store.list_documents_extended(filters=SearchFilters(profile="joriel"))
    technostik = store.list_documents_extended(
        filters=SearchFilters(profile="technostik")
    )
    assert [d["source_id"] for d in joriel] == ["v1"]
    assert [d["source_id"] for d in technostik] == ["v2"]


def test_pool_item_profile_roundtrip():
    store = SQLAlchemyStore(":memory:")
    store.upsert_pool_item("youtube", "p1", "pending", {}, profile="joriel")
    items = store.get_pool_items("youtube", status=None)
    assert items[0]["profile"] == "joriel"
    assert pool_row(items[0])["profile"] == "joriel"


class _FakeStore:
    def __init__(self, docs=None):
        self.docs = docs or []

    def list_profiles(self):
        return sorted({d["profile"] for d in self.docs if d.get("profile")})

    def list_documents_extended(self, source=None, filters=None, order_by="date",
                                reverse=False, limit=1000):
        rows = list(self.docs)
        if filters and filters.profile:
            rows = [d for d in rows if d.get("profile") == filters.profile]
        return rows

    def get_pool_items(self, source=None, status=None):
        return []


def _client(monkeypatch, store):
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import webux.corpus_browser.register as mod

    monkeypatch.setattr(
        mod, "_backend_factory",
        lambda: {"config": {}, "store": store, "engine": None, "plugins": {}},
    )
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/corpus_browser")
    return TestClient(app)


def test_browse_profiles_endpoint(monkeypatch):
    store = _FakeStore([
        {"handle": "youtube:v1", "source_plugin": "youtube", "source_id": "v1",
         "title": "One", "profile": "joriel", "metadata": {}, "raw_text": "x"},
        {"handle": "youtube:v2", "source_plugin": "youtube", "source_id": "v2",
         "title": "Two", "profile": "technostik", "metadata": {}, "raw_text": "y"},
    ])
    client = _client(monkeypatch, store)
    assert client.get("/api/corpus_browser/profiles").json() == {
        "profiles": ["joriel", "technostik"]
    }
    data = client.get("/api/corpus_browser/browse?profile=joriel").json()
    assert [i["source_id"] for i in data["items"]] == ["v1"]
