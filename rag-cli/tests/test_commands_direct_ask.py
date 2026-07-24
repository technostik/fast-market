from __future__ import annotations

from core.extractors import extract_markdown
from core.tree_builder import build_md_tree
from core.tree_search import _build_flat_tree, run_agentic_search
from storage.store import RagStore, create_memory_engine, make_session_factory
from storage.models import SourceType
from pathlib import Path


class FakeTreeNode:
    def __init__(self, id, node_id, parent_id, title, summary="", start_index=0, end_index=0):
        self.id = id
        self.node_id = node_id
        self.parent_id = parent_id
        self.title = title
        self.summary = summary
        self.start_index = start_index
        self.end_index = end_index


def test_direct_ask_leaves_no_rows_without_keep(sample_md_path: Path):
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    store = RagStore(sf)

    extracted = extract_markdown(sample_md_path)
    tree = build_md_tree(extracted.full_text)

    doc = store.upsert_document(
        handle="direct-test",
        source_type=SourceType.local_file,
        source_ref=str(sample_md_path),
        content_hash=extracted.content_hash,
        title=extracted.title,
    )
    store.persist_tree(doc.id, tree)

    from storage.models import Base
    with engine.connect() as conn:
        tree_count = conn.execute(Base.metadata.tables["tree_nodes"].select()).fetchall()
        doc_count = conn.execute(Base.metadata.tables["documents"].select()).fetchall()
    assert len(tree_count) > 0
    assert len(doc_count) == 1

    store.purge_document(doc.id)

    with engine.connect() as conn:
        tree_count = conn.execute(Base.metadata.tables["tree_nodes"].select()).fetchall()
        doc_count = conn.execute(Base.metadata.tables["documents"].select()).fetchall()
    assert len(tree_count) == 0
    assert len(doc_count) == 0


def test_direct_ask_keep_leaves_document(sample_md_path: Path):
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    store = RagStore(sf)

    extracted = extract_markdown(sample_md_path)
    tree = build_md_tree(extracted.full_text)

    doc = store.upsert_document(
        handle="keep-test",
        source_type=SourceType.local_file,
        source_ref=str(sample_md_path),
        content_hash=extracted.content_hash,
        title=extracted.title,
    )
    store.persist_tree(doc.id, tree)

    from storage.models import Base
    with engine.connect() as conn:
        doc_count = conn.execute(Base.metadata.tables["documents"].select()).fetchall()
        member_count = conn.execute(Base.metadata.tables["collection_members"].select()).fetchall()
    assert len(doc_count) == 1
    assert len(member_count) == 0
