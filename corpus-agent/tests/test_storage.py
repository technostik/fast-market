from __future__ import annotations

from core.models import Chunk, Document


def test_upsert_idempotent(store):
    doc = Document(source_plugin="obsidian", source_id="1", title="t", raw_text="hello")
    assert store.upsert_document(doc, "h1") is True
    assert store.upsert_document(doc, "h1") is False


def test_keyword_search(store):
    doc = Document(source_plugin="obsidian", source_id="1", title="t", raw_text="hello world")
    store.upsert_document(doc, "h1")
    chunk = Chunk("obsidian", "1", 0, "hello world", "c1", [1.0, 0.0])
    store.replace_chunks("obsidian", "1", [chunk])
    results = store.keyword_search("hello", 5)
    assert len(results) == 1
