from __future__ import annotations

from core.extractors import extract_markdown
from core.tree_builder import build_md_tree
from core.tree_search import _build_flat_tree, run_agentic_search
from storage.store import RagStore, create_memory_engine, make_session_factory
from storage.models import SourceType
from pathlib import Path


def test_direct_ask_pipeline_persists_text_and_links(sample_md_path: Path):
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    store = RagStore(sf)

    extracted = extract_markdown(sample_md_path)
    tree = build_md_tree(extracted.full_text)

    doc = store.upsert_document(
        handle="pipeline-test",
        source_type=SourceType.local_file,
        source_ref=str(sample_md_path),
        content_hash=extracted.content_hash,
        title=extracted.title,
    )
    node_count = store.persist_tree(doc.id, tree)
    assert node_count > 0

    tree_nodes = store.get_tree_nodes_for_document(doc.id)
    assert len(tree_nodes) > 0

    for tn in tree_nodes:
        assert hasattr(tn, "text"), f"TreeNode {tn.node_id} missing text attribute"
        assert isinstance(tn.text, str)

    tree_by_id, nid_map = _build_flat_tree(tree_nodes)

    assert len(tree_by_id) == len(tree_nodes)
    assert len(nid_map) == len(tree_nodes)

    root_nodes = [n for n in tree_by_id.values() if n["parent_node_id"] is None]
    assert len(root_nodes) == 1
    assert root_nodes[0]["title"] == "Sample Document"

    root_data = root_nodes[0]
    assert len(root_data["child_node_ids"]) >= 3

    for child_nid in root_data["child_node_ids"]:
        child = tree_by_id[child_nid]
        assert child["parent_node_id"] == root_data["node_id"]

    for nid, data in tree_by_id.items():
        if data["parent_node_id"]:
            parent = tree_by_id[data["parent_node_id"]]
            assert nid in parent["child_node_ids"]


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


def test_headingless_markdown_builds_single_root_node():
    content = (
        "Mes preceptes sont simples.\n"
        "Toujours rester curieux.\n"
        "Jamais abandonner.\n"
    )
    tree = build_md_tree(content)

    assert len(tree) == 1
    node = tree[0]
    assert node["node_id"] == "0001"
    assert node["title"] == "Document"
    assert "Mes preceptes" in node["text"]


def test_headingless_markdown_list_children_returns_root():
    from core.tree_search import _build_flat_tree, _execute_list_children

    content = (
        "Mes preceptes sont simples.\n"
        "Toujours rester curieux.\n"
    )
    tree = build_md_tree(content)

    engine = create_memory_engine()
    sf = make_session_factory(engine)
    store = RagStore(sf)

    doc = store.upsert_document(
        handle="no-headings",
        source_type=SourceType.local_file,
        source_ref="/tmp/no-headings.md",
        content_hash="abc123",
        title="no-headings",
    )
    store.persist_tree(doc.id, tree)

    tree_nodes = store.get_tree_nodes_for_document(doc.id)
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)

    result = _execute_list_children("root", tree_by_id, nid_map)
    import json
    data = json.loads(result)
    assert len(data["children"]) == 1
    assert data["children"][0]["node_id"] == "0001"


def test_direct_ask_directory_combines_trees(tmp_path):
    (tmp_path / "doc1.md").write_text("# Doc One\n\nContent one.")
    (tmp_path / "doc2.md").write_text("# Doc Two\n\nContent two.")

    from core.extractors import discover_files

    files = discover_files(tmp_path)
    assert len(files) == 2

    engine = create_memory_engine()
    sf = make_session_factory(engine)
    store = RagStore(sf)

    all_tree_by_id = {}
    all_nid_map = {}
    for idx, f in enumerate(files):
        prefix = f"doc{idx}_"
        from core.extractors import extract_local_file
        extracted = extract_local_file(f)
        tree = build_md_tree(extracted.full_text)
        doc = store.upsert_document(
            handle=f"test:{f.name}:{f.stat().st_size}",
            source_type=SourceType.local_file,
            source_ref=str(f),
            content_hash=extracted.content_hash,
            title=extracted.title,
        )
        store.persist_tree(doc.id, tree)
        tree_nodes = store.get_tree_nodes_for_document(doc.id)
        tree_by_id, nid_map = _build_flat_tree(tree_nodes, node_id_prefix=prefix)
        all_tree_by_id.update(tree_by_id)
        all_nid_map.update(nid_map)

    root_nodes = [n for n in all_tree_by_id.values() if n.get("parent_node_id") is None]
    assert len(root_nodes) == 2
    titles = {n["title"] for n in root_nodes}
    assert "Doc One" in titles
    assert "Doc Two" in titles
