from __future__ import annotations

from datetime import datetime

import pytest

from core.models import Document
from core.sync_engine import SyncEngine
from core.sync_errors import MissingInputFieldError, NetworkError, TranscriptUnavailableError
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


class FakeOp:
    name = "fake"
    field = "summary"

    def __init__(self, value="summarized"):
        self.value = value
        self.calls = 0

    def run(self, doc: dict):
        self.calls += 1
        return self.value


class FailingOp:
    name = "fake"
    field = "summary"

    def run(self, doc: dict):
        raise MissingInputFieldError("missing raw_text")


def _seed_doc(store, source_id, plugin="obsidian", title=None):
    store.upsert_document(
        Document(
            source_plugin=plugin,
            source_id=source_id,
            handle=f"{plugin}-{source_id}",
            title=title or f"Doc {source_id}",
            raw_text="# H\ntext " * 3,
        ),
        "hash-" + source_id,
    )


def test_sync_field_fills_declared_field(store, embedder):
    store.create_field_definition("summary")
    _seed_doc(store, "a")
    _seed_doc(store, "b")
    engine = SyncEngine(store, embedder)
    op = FakeOp()

    res = engine.sync_field("summary", op, source="obsidian")

    assert res.indexed == 2
    assert op.calls == 2
    assert store.get_document("obsidian", "a")["metadata"]["summary"] == "summarized"
    assert store.get_document("obsidian", "b")["metadata"]["summary"] == "summarized"


def test_sync_field_skips_docs_that_already_have_value(store, embedder):
    store.create_field_definition("summary")
    _seed_doc(store, "a")
    store.set_document_field("obsidian", "a", "summary", "existing")
    engine = SyncEngine(store, embedder)
    op = FakeOp()

    res = engine.sync_field("summary", op, source="obsidian")

    assert res.indexed == 0
    assert op.calls == 0


def test_sync_field_handles_filter(store, embedder):
    store.create_field_definition("summary")
    _seed_doc(store, "a")
    _seed_doc(store, "b")
    engine = SyncEngine(store, embedder)
    handle_a = store.get_document("obsidian", "a")["handle"]
    op = FakeOp()

    res = engine.sync_field("summary", op, source="obsidian", handles=[handle_a])

    assert res.indexed == 1
    assert op.calls == 1
    assert store.get_document("obsidian", "a")["metadata"]["summary"] == "summarized"
    assert store.get_document("obsidian", "b")["metadata"].get("summary") is None


def test_sync_field_undeclared_field_raises(store, embedder):
    _seed_doc(store, "a")
    engine = SyncEngine(store, embedder)
    with pytest.raises(ValueError):
        engine.sync_field("summary", FakeOp(), source="obsidian")


def test_sync_field_records_failure(store, embedder):
    store.create_field_definition("summary")
    _seed_doc(store, "a")
    _seed_doc(store, "b")
    engine = SyncEngine(store, embedder)

    res = engine.sync_field("summary", FailingOp(), source="obsidian")

    assert res.indexed == 0
    assert len(res.failures) == 2
    failures = store.list_failures("obsidian")
    assert all(f["error_type"] == "permanent" for f in failures)


# ── sync_documents: transcript resync of already-indexed docs ─────────────────


class ResyncPlugin(SourcePlugin):
    name = "youtube"

    def __init__(self, texts):
        self.texts = texts  # source_id -> list of transcript contents, in order
        self.calls = {}

    def list_items(self, limit, known_id_dates=None, debug=False):
        return []

    def fetch(self, item_meta):
        sid = item_meta.source_id
        self.calls[sid] = self.calls.get(sid, 0) + 1
        pool = self.texts[sid]
        raw = pool[min(self.calls[sid] - 1, len(pool) - 1)]
        return Document(
            source_plugin="youtube",
            source_id=sid,
            title=item_meta.metadata.get("title", sid),
            raw_text=raw,
            metadata=item_meta.metadata,
        )


def test_sync_documents_refetches_changed_transcript(store, embedder):
    store.upsert_document(
        Document(source_plugin="youtube", source_id="v1", handle="yt-v1",
                 title="V1", raw_text="old transcript"),
        "hash-old",
    )
    plugin = ResyncPlugin({"v1": ["new transcript"]})
    engine = SyncEngine(store, embedder)

    res = engine.sync_documents(plugin, ["yt-v1"])

    assert res.processed == 1
    assert res.indexed == 1
    assert store.get_document("youtube", "v1")["raw_text"] == "new transcript"


def test_sync_documents_skips_unchanged_transcript(store, embedder):
    same = "identical transcript"
    store.upsert_document(
        Document(source_plugin="youtube", source_id="v1", handle="yt-v1",
                 title="V1", raw_text=same),
        embedder.hash_text(same),
    )
    plugin = ResyncPlugin({"v1": [same]})
    engine = SyncEngine(store, embedder)

    res = engine.sync_documents(plugin, ["yt-v1"])

    assert res.indexed == 0
    assert res.skipped == 1


def test_sync_documents_ignores_handles_of_other_sources(store, embedder):
    store.upsert_document(
        Document(source_plugin="obsidian", source_id="a", handle="ob-a",
                 title="A", raw_text="note"),
        "hash-note",
    )
    plugin = ResyncPlugin({"v1": ["transcript"]})
    engine = SyncEngine(store, embedder)

    res = engine.sync_documents(plugin, ["ob-a", "missing-handle"])

    assert res.processed == 0
    assert res.indexed == 0
