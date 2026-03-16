from __future__ import annotations

from datetime import datetime

from core.sync_engine import SyncEngine
from plugins.base import ItemMeta, SourcePlugin
from core.models import Document


class P(SourcePlugin):
    name = "obsidian"

    def list_items(self, limit: int, since=None):
        return [ItemMeta("a", datetime.utcnow())]

    def fetch(self, item_meta: ItemMeta):
        return Document(source_plugin="obsidian", source_id="a", title="A", raw_text="# H\ntext")


def test_sync_engine_sync(store, embedder):
    engine = SyncEngine(store, embedder)
    res = engine.sync(P(), mode="backfill", limit=1)
    assert res.indexed == 1
