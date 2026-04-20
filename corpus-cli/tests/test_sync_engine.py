from __future__ import annotations

from datetime import datetime

from core.models import Document
from core.sync_engine import SyncEngine
from core.sync_errors import NetworkError, TranscriptUnavailableError
from plugins.base import ItemMeta, SourcePlugin


class P(SourcePlugin):
    name = "obsidian"

    def list_items(self, limit: int, known_id_dates=None, debug: bool = False):
        return [ItemMeta("a", datetime.utcnow())]

    def fetch(self, item_meta: ItemMeta):
        return Document(
            source_plugin="obsidian", source_id="a", title="A", raw_text="# H\ntext"
        )


class FlakyPlugin(SourcePlugin):
    name = "youtube"

    def __init__(self):
        self.calls = 0

    def list_items(self, limit: int, known_id_dates=None, debug: bool = False):
        return [ItemMeta("bad", datetime.utcnow())]

    def fetch(self, item_meta: ItemMeta):
        self.calls += 1
        if self.calls == 1:
            raise NetworkError("temporary")
        return Document(
            source_plugin="youtube", source_id="bad", title="Recovered", raw_text="ok"
        )


class PermanentFailurePlugin(SourcePlugin):
    name = "youtube"

    def __init__(self):
        self.calls = 0

    def list_items(self, limit: int, known_id_dates=None, debug: bool = False):
        return [ItemMeta("perm", datetime.utcnow())]

    def fetch(self, item_meta: ItemMeta):
        self.calls += 1
        raise TranscriptUnavailableError("no transcript")


def test_sync_engine_sync(store, embedder):
    engine = SyncEngine(store, embedder)
    res = engine.sync(P(), mode="backfill", limit=1)
    assert res.indexed == 1


def test_transient_failure_is_retried_and_cleared(store, embedder):
    plugin = FlakyPlugin()
    engine = SyncEngine(store, embedder)

    first = engine.sync(plugin, mode="backfill", limit=1)
    assert first.failures
    failures = store.list_failures("youtube")
    assert failures[0]["error_type"] == "transient"

    second = engine.sync(plugin, mode="backfill", limit=1)
    assert second.indexed == 1
    assert store.list_failures("youtube") == []


def test_permanent_failure_is_skipped_on_next_run(store, embedder):
    plugin = PermanentFailurePlugin()
    engine = SyncEngine(store, embedder)

    first = engine.sync(plugin, mode="backfill", limit=1)
    assert first.failures
    assert plugin.calls == 1

    second = engine.sync(plugin, mode="backfill", limit=1)
    assert second.failures == []
    assert plugin.calls == 1
