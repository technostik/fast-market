"""Multi-profile support: the `profile` column and profile-scoped browsing.

Each profile owns its corpus DB, so the browser must open the profile selected
in the webux toolbar (passed as `?profile=`), not the server process's active
profile. The Alembic migration (0006) backfills pre-existing rows to "joriel";
that path is exercised on real files, not by these unit tests.
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


def test_upsert_document_defaults_to_active_profile(monkeypatch):
    monkeypatch.setenv("FASTMARKET_PROFILE", "technostik")
    store = SQLAlchemyStore(":memory:")
    store.upsert_document(_doc("v1", ""), "h1")
    assert store.get_document("youtube", "v1")["profile"] == "technostik"


def test_store_constructor_profile_tags_writes(monkeypatch):
    # A store opened for a profile tags rows with it even if the process env is
    # a different profile (the browser's background jobs rely on this).
    monkeypatch.setenv("FASTMARKET_PROFILE", "joriel")
    store = SQLAlchemyStore(":memory:", profile="technostik")
    store.upsert_document(_doc("v1", ""), "h1")
    assert store.get_document("youtube", "v1")["profile"] == "technostik"


def test_pool_item_profile_roundtrip():
    store = SQLAlchemyStore(":memory:")
    store.upsert_pool_item("youtube", "p1", "pending", {}, profile="joriel")
    items = store.get_pool_items("youtube", status=None)
    assert items[0]["profile"] == "joriel"
    assert pool_row(items[0])["profile"] == "joriel"


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


class _FakeStore:
    def __init__(self, docs=None):
        self.docs = docs or []

    def list_documents_extended(self, source=None, filters=None, order_by="date",
                                reverse=False, limit=1000):
        return list(self.docs)

    def get_pool_items(self, source=None, status=None):
        return []


def test_browse_uses_requested_profile(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import webux.corpus_browser.register as mod

    seen: list[str | None] = []

    def _factory(profile=None):
        seen.append(profile)
        return {
            "config": {}, "store": _FakeStore(), "engine": None,
            "plugins": {}, "profile": profile,
        }

    monkeypatch.setattr(mod, "_backend_factory", _factory)
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/corpus_browser")
    client = TestClient(app)

    assert client.get("/api/corpus_browser/browse?profile=technostik").status_code == 200
    assert seen == ["technostik"]

    # POST endpoints inherit the profile from the query string too (the frontend
    # fetch wrapper appends it to every request, body or not).
    seen.clear()
    assert client.post(
        "/api/corpus_browser/scan?profile=technostik", json={"source": "all"}
    ).status_code == 200
    assert "technostik" in seen
