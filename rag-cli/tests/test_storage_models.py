from __future__ import annotations

import pytest
from storage.store import RagStore, create_memory_engine, make_session_factory
from storage.models import SourceType


@pytest.fixture
def store():
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    return RagStore(sf)


def test_create_and_list_collections(store: RagStore):
    store.create_collection("test-coll", "A test collection")
    collections = store.list_collections()
    assert len(collections) == 1
    assert collections[0]["name"] == "test-coll"


def test_create_duplicate_collection_raises(store: RagStore):
    store.create_collection("dup")
    with pytest.raises(ValueError, match="already exists"):
        store.create_collection("dup")


def test_delete_collection(store: RagStore):
    store.create_collection("to-delete")
    assert store.delete_collection("to-delete") is True
    assert store.delete_collection("nonexistent") is False


def test_get_collection(store: RagStore):
    store.create_collection("find-me", "desc")
    coll = store.get_collection("find-me")
    assert coll is not None
    assert coll.name == "find-me"
    assert store.get_collection("nope") is None


def test_upsert_document(store: RagStore):
    doc = store.upsert_document(
        handle="test-handle",
        source_type=SourceType.local_file,
        source_ref="/tmp/test.pdf",
        content_hash="abc123",
        title="Test Doc",
    )
    assert doc.handle == "test-handle"
    found = store.get_document_by_handle("test-handle")
    assert found is not None


def test_upsert_document_update(store: RagStore):
    store.upsert_document(
        handle="h1",
        source_type=SourceType.local_file,
        source_ref="/tmp/a.pdf",
        content_hash="old",
        title="Old Title",
    )
    doc = store.upsert_document(
        handle="h1",
        source_type=SourceType.local_file,
        source_ref="/tmp/a.pdf",
        content_hash="new",
        title="New Title",
    )
    assert doc.title == "New Title"
    assert doc.content_hash == "new"


def test_persist_and_get_tree(store: RagStore):
    doc = store.upsert_document(
        handle="tree-doc",
        source_type=SourceType.local_file,
        source_ref="/tmp/t.pdf",
        content_hash="h",
        title="Tree Doc",
    )
    tree = [
        {
            "node_id": "0001",
            "title": "Root",
            "summary": "Root summary",
            "start_index": 1,
            "end_index": 5,
            "nodes": [
                {
                    "node_id": "0002",
                    "title": "Child",
                    "summary": "Child summary",
                    "start_index": 1,
                    "end_index": 3,
                    "nodes": [],
                }
            ],
        }
    ]
    count = store.persist_tree(doc.id, tree)
    assert count == 2
    nodes = store.get_tree_nodes_for_document(doc.id)
    assert len(nodes) == 2


def test_collection_member_and_isolation(store: RagStore):
    coll = store.create_collection("iso-test")
    doc = store.upsert_document(
        handle="shared-doc",
        source_type=SourceType.local_file,
        source_ref="/tmp/s.pdf",
        content_hash="h",
        title="Shared",
    )
    store.persist_tree(
        doc.id,
        [
            {"node_id": "0001", "title": "Root", "summary": "", "start_index": 1, "end_index": 5, "nodes": []},
            {"node_id": "0002", "title": "Ch", "summary": "", "start_index": 1, "end_index": 2, "nodes": []},
        ],
    )
    store.add_collection_member(coll["id"], doc.id, root_node_id=None)
    members = store.get_collection_members(coll["id"])
    assert len(members) == 1


def test_get_reachable_node_ids_whole_document(store: RagStore):
    coll = store.create_collection("reach-test")
    doc = store.upsert_document(
        handle="reach-doc",
        source_type=SourceType.local_file,
        source_ref="/tmp/r.pdf",
        content_hash="h",
        title="Reach",
    )
    store.persist_tree(
        doc.id,
        [
            {"node_id": "0001", "title": "A", "summary": "", "start_index": 1, "end_index": 2, "nodes": [
                {"node_id": "0002", "title": "B", "summary": "", "start_index": 1, "end_index": 1, "nodes": []},
            ]},
        ],
    )
    store.add_collection_member(coll["id"], doc.id, root_node_id=None)
    reachable = store.get_reachable_node_ids(coll["id"], doc.id)
    assert "0001" in reachable
    assert "0002" in reachable


def test_get_reachable_node_ids_scoped(store: RagStore):
    coll = store.create_collection("scope-test")
    doc = store.upsert_document(
        handle="scope-doc",
        source_type=SourceType.local_file,
        source_ref="/tmp/s2.pdf",
        content_hash="h",
        title="Scope",
    )
    tree = store.persist_tree(
        doc.id,
        [
            {"node_id": "0001", "title": "Root", "summary": "", "start_index": 1, "end_index": 5, "nodes": [
                {"node_id": "0002", "title": "Ch A", "summary": "", "start_index": 1, "end_index": 2, "nodes": []},
                {"node_id": "0003", "title": "Ch B", "summary": "", "start_index": 3, "end_index": 5, "nodes": []},
            ]},
        ],
    )
    nodes = store.get_tree_nodes_for_document(doc.id)
    root_node = [n for n in nodes if n.node_id == "0002"][0]
    store.add_collection_member(coll["id"], doc.id, root_node_id=root_node.id)
    reachable = store.get_reachable_node_ids(coll["id"], doc.id)
    assert "0002" in reachable
    assert "0003" not in reachable


def test_remove_collection_member(store: RagStore):
    coll = store.create_collection("rm-test")
    doc = store.upsert_document(
        handle="rm-doc",
        source_type=SourceType.local_file,
        source_ref="/tmp/rm.pdf",
        content_hash="h",
        title="RM",
    )
    store.add_collection_member(coll["id"], doc.id)
    assert store.remove_collection_member(coll["id"], doc.id) is True
    assert store.remove_collection_member(coll["id"], doc.id) is False


def test_purge_document(store: RagStore):
    doc = store.upsert_document(
        handle="purge-me",
        source_type=SourceType.local_file,
        source_ref="/tmp/p.pdf",
        content_hash="h",
        title="Purge",
    )
    assert store.purge_document(doc.id) is True
    assert store.get_document_by_handle("purge-me") is None


def test_index_run(store: RagStore):
    doc = store.upsert_document(
        handle="run-doc",
        source_type=SourceType.local_file,
        source_ref="/tmp/ir.pdf",
        content_hash="h",
        title="Run",
    )
    run = store.create_index_run(doc.id, model_used="test-model", is_ephemeral=0)
    assert run.status.value == "running"
    store.finish_index_run(run.id, "success")
    run2 = store.create_index_run(doc.id, is_ephemeral=1)
    assert run2.is_ephemeral == 1
