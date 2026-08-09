from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pool_enrich import enrich_pool_items


class _FakeStore:
    """In-memory stand-in for SQLAlchemyStore pool operations."""

    def __init__(self, items):
        self.items = items

    def get_pool_items(self, source=None, status=None):
        return [
            it
            for it in self.items
            if (source is None or it["source_plugin"] == source)
            and (status is None or it["status"] == status)
        ]

    def upsert_pool_item(self, plugin_name, source_id, status, metadata,
                         added_at=None, synced_at=None):
        self.items = [
            it
            for it in self.items
            if not (it["source_plugin"] == plugin_name and it["source_id"] == source_id)
        ]
        self.items.append(
            {
                "source_plugin": plugin_name,
                "source_id": source_id,
                "status": status,
                "metadata": metadata,
                "added_at": added_at,
                "synced_at": synced_at,
            }
        )
        return False


def _item(sid, status, **meta):
    return {
        "source_plugin": "youtube",
        "source_id": sid,
        "status": status,
        "metadata": {"title": f"Title {sid}", **meta},
        "added_at": "2026-08-01T00:00:00",
        "synced_at": None,
    }


@pytest.fixture
def store():
    return _FakeStore(
        [
            _item("v1", "pending"),
            _item("v2", "failed"),
            _item("v3", "excluded"),
            _item("v4", "synced"),
            _item("v5", "pending", duration_seconds=600),
        ]
    )


def _meta(sid, cookies=None):
    return {
        "duration_seconds": 330,
        "view_count": 1234,
        "channel_title": f"Channel {sid}",
        "fetched_at": "2026-08-09T00:00:00",
    }


def test_default_enriches_all_non_synced(store):
    result = enrich_pool_items(store, "youtube", fetch_one=_meta)
    assert result.processed == 4
    assert result.enriched == 4
    assert result.failed == 0
    by_id = {it["source_id"]: it for it in store.items}
    assert by_id["v1"]["metadata"]["view_count"] == 1234
    assert by_id["v4"]["status"] == "synced"  # untouched
    assert "view_count" not in by_id["v4"]["metadata"]


def test_metadata_merged_preserving_existing(store):
    enrich_pool_items(store, "youtube", fetch_one=_meta)
    by_id = {it["source_id"]: it for it in store.items}
    assert by_id["v5"]["metadata"]["duration_seconds"] == 330  # real value wins
    assert by_id["v5"]["metadata"]["title"] == "Title v5"  # scan title kept
    assert by_id["v5"]["metadata"]["view_count"] == 1234  # new key added


def test_status_and_added_at_preserved(store):
    enrich_pool_items(store, "youtube", fetch_one=_meta)
    by_id = {it["source_id"]: it for it in store.items}
    assert by_id["v3"]["status"] == "excluded"
    assert by_id["v3"]["added_at"] == "2026-08-01T00:00:00"


def test_unchanged_metadata_counts_skipped(store):
    def same(sid, cookies=None):
        return dict(next(i for i in store.items if i["source_id"] == sid)["metadata"])

    result = enrich_pool_items(store, "youtube", fetch_one=same)
    assert result.enriched == 0
    assert result.skipped == 4


def test_failures_reported(store):
    def flaky(sid, cookies=None):
        if sid == "v2":
            raise RuntimeError("network down")
        if sid == "v3":
            return {}
        return _meta(sid)

    result = enrich_pool_items(store, "youtube", fetch_one=flaky)
    assert result.failed == 2
    assert result.enriched == 2
    ids = {f.source_id for f in result.failures}
    assert ids == {"v2", "v3"}


def test_source_ids_restricts(store):
    result = enrich_pool_items(store, "youtube", source_ids=["v1", "v2"], fetch_one=_meta)
    assert result.processed == 2
    by_id = {it["source_id"]: it for it in store.items}
    assert "view_count" in by_id["v1"]["metadata"]
    assert "view_count" not in by_id["v3"]["metadata"]


def test_source_ids_unknown_ids_ignored(store):
    result = enrich_pool_items(store, "youtube", source_ids=["ghost", "v1"], fetch_one=_meta)
    assert result.processed == 1
    assert result.enriched == 1


def test_limit_caps_processed(store):
    result = enrich_pool_items(store, "youtube", limit=2, fetch_one=_meta)
    assert result.processed == 2
    assert result.enriched == 2
    by_id = {it["source_id"]: it for it in store.items}
    assert "view_count" in by_id["v1"]["metadata"]
    assert "view_count" not in by_id["v5"]["metadata"]


def test_no_pool_items(store):
    store.items = []
    result = enrich_pool_items(store, "youtube", fetch_one=_meta)
    assert result.processed == 0
    assert result.enriched == 0


def test_duration_zero_does_not_overwrite(store):
    def zero_duration(sid, cookies=None):
        return {"duration_seconds": 0, "view_count": 5}

    enrich_pool_items(store, "youtube", fetch_one=zero_duration)
    by_id = {it["source_id"]: it for it in store.items}
    assert by_id["v5"]["metadata"]["duration_seconds"] == 600
