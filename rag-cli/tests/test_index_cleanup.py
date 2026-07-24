from __future__ import annotations

from commands.index.register import collect_stats, drop_and_recreate
from storage.models import Base, SourceType
from storage.store import RagStore, create_memory_engine, make_session_factory


def _make_store_with_data():
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    store = RagStore(sf)

    coll = store.create_collection("test-coll")
    doc = store.upsert_document(
        handle="test-doc",
        source_type=SourceType.local_file,
        source_ref="/tmp/test.md",
        content_hash="abc",
        title="Test",
    )
    store.persist_tree(
        doc.id,
        [
            {"node_id": "0001", "title": "Root", "text": "root text", "summary": "", "start_index": 1, "end_index": 5, "nodes": [
                {"node_id": "0002", "title": "Child", "text": "child text", "summary": "", "start_index": 1, "end_index": 2, "nodes": []},
            ]},
        ],
    )
    store.add_collection_member(coll["id"], doc.id)
    return store, engine


def test_collect_stats():
    store, engine = _make_store_with_data()
    stats = collect_stats(store, engine)
    assert stats["total_collections"] == 1
    assert stats["total_docs"] == 1
    assert stats["total_nodes"] == 2
    assert stats["total_members"] == 1


def test_drop_and_recreate_clears_all():
    store, engine = _make_store_with_data()
    stats_before = collect_stats(store, engine)
    assert stats_before["total_docs"] == 1

    drop_and_recreate(engine)

    stats_after = collect_stats(store, engine)
    assert stats_after["total_collections"] == 0
    assert stats_after["total_docs"] == 0
    assert stats_after["total_nodes"] == 0
    assert stats_after["total_members"] == 0
    assert stats_after["total_runs"] == 0


def test_cleanup_empty_index():
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    store = RagStore(sf)

    stats = collect_stats(store, engine)
    assert stats["total_docs"] == 0


def test_migration_adds_missing_text_column():
    """Simulate a DB created before the text column was added."""
    from sqlalchemy import text, create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE collections (id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')"))
        conn.execute(text("CREATE TABLE documents (id INTEGER PRIMARY KEY, handle TEXT NOT NULL, source_type TEXT NOT NULL, source_ref TEXT NOT NULL, content_hash TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')"))
        conn.execute(text("CREATE TABLE tree_nodes (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, node_id TEXT NOT NULL, parent_id INTEGER, title TEXT NOT NULL DEFAULT '', start_index INTEGER NOT NULL DEFAULT 0, end_index INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '', order_index INTEGER NOT NULL DEFAULT 0, tags TEXT)"))
        conn.execute(text("CREATE TABLE collection_members (id INTEGER PRIMARY KEY, collection_id INTEGER NOT NULL, document_id INTEGER NOT NULL, root_node_id INTEGER, added_at TEXT NOT NULL DEFAULT '')"))
        conn.execute(text("CREATE TABLE index_runs (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, model_used TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL DEFAULT '', finished_at TEXT, status TEXT NOT NULL DEFAULT 'running', error TEXT, is_ephemeral INTEGER NOT NULL DEFAULT 0)"))

    sf = make_session_factory(engine)
    store = RagStore(sf)
    store.ensure_tables(engine)

    from sqlalchemy import inspect
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("tree_nodes")}
    assert "text" in columns
