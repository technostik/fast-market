from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pool_rows import (
    POOL_HANDLE_PREFIX,
    NOT_SYNCED_STATES,
    pool_row,
    row_sort_key,
    select_pool_rows,
)


class _FakeFilters:
    def __init__(self, min_duration=None, max_duration=None, since=None, until=None):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.since = since
        self.until = until


class _FakeStore:
    def __init__(self, items):
        self.items = items

    def get_pool_items(self, source=None, status=None):
        return [
            it
            for it in self.items
            if (source is None or it["source_plugin"] == source)
            and (status is None or it["status"] == status)
        ]


def _item(sid, status, title="Video X", published="2026-01-02T00:00:00Z", **meta):
    return {
        "source_plugin": "youtube",
        "source_id": sid,
        "status": status,
        "metadata": {"title": title, "published_at": published, **meta},
        "added_at": "2026-08-01T00:00:00",
        "synced_at": None,
    }


@pytest.fixture
def store():
    return _FakeStore(
        [
            _item("v1", "pending", "Pending One"),
            _item("v2", "failed", "Failed Two"),
            _item("v3", "excluded", "Excluded Three"),
            _item("v4", "synced", "Synced Four"),
        ]
    )


def test_pool_row_shape(store):
    row = pool_row(store.items[0])
    assert row["handle"] == f"{POOL_HANDLE_PREFIX}youtube:v1"
    assert row["title"] == "Pending One"
    assert row["pool_status"] == "pending"
    assert row["scan_at"] == "2026-08-01T00:00:00"
    assert row["raw_text"] is None


def test_pool_row_duration_from_metadata(store):
    item = _item("v5", "pending", duration_seconds="330")
    assert pool_row(item)["duration_seconds"] == 330
    item = _item("v6", "pending", duration_seconds="junk")
    assert pool_row(item)["duration_seconds"] is None


def test_select_pool_rows_synced_is_empty(store):
    assert select_pool_rows(store, None, "synced") == []
    assert select_pool_rows(store, None, None) == []


def test_select_pool_rows_states(store):
    pending = select_pool_rows(store, None, "pending")
    assert [r["pool_status"] for r in pending] == ["pending"]

    failed = select_pool_rows(store, None, "failed")
    assert [r["pool_status"] for r in failed] == ["failed"]

    excluded = select_pool_rows(store, None, "excluded")
    assert [r["pool_status"] for r in excluded] == ["excluded"]

    non_synced = select_pool_rows(store, None, "not-synced")
    assert [r["pool_status"] for r in non_synced] == list(NOT_SYNCED_STATES)

    all_rows = select_pool_rows(store, None, "all")
    assert {r["pool_status"] for r in all_rows} == set(NOT_SYNCED_STATES)


def test_select_pool_rows_source_filter(store):
    rows = select_pool_rows(store, "obsidian", "all")
    assert rows == []


def test_select_pool_rows_filters(store):
    rows = select_pool_rows(
        store, None, "not-synced", _FakeFilters(min_duration=1)
    )
    # durations are unknown (None) → not classifiable, so they stay visible.
    assert len(rows) == 3


def test_pool_matches_duration_filter_only_when_known(store):
    from core.pool_rows import pool_matches

    known_short = pool_row(_item("v7", "pending", duration_seconds="30"))
    known_long = pool_row(_item("v8", "pending", duration_seconds="600"))
    unknown = pool_row(_item("v9", "pending"))

    # "exclude shorts" → min_duration 181s
    f = _FakeFilters(min_duration=181)
    assert not pool_matches(known_short, f)   # short → hidden
    assert pool_matches(known_long, f)        # long → shown
    assert pool_matches(unknown, f)           # unknown → shown, not emptied


def test_row_sort_key(store):
    rows = [pool_row(it) for it in store.items]
    by_title = sorted(rows, key=lambda r: row_sort_key(r, "title"), reverse=True)
    assert by_title[0]["title"] == "Synced Four"
    by_date = sorted(rows, key=lambda r: row_sort_key(r, "date"), reverse=True)
    assert by_date[0]["title"] == "Pending One"
    by_field = sorted(rows, key=lambda r: row_sort_key(r, "field:title"))
    assert by_field[0]["title"] == "Excluded Three"