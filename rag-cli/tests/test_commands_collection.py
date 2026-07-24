from __future__ import annotations

import pytest
from storage.store import RagStore, create_memory_engine, make_session_factory
from storage.models import SourceType


@pytest.fixture
def store():
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    return RagStore(sf)


class TestCollectionCommands:
    def test_create_and_list(self, store: RagStore):
        store.create_collection("my-coll", description="Test")
        collections = store.list_collections()
        assert len(collections) == 1
        assert collections[0]["name"] == "my-coll"
        assert collections[0]["description"] == "Test"

    def test_list_empty(self, store: RagStore):
        assert store.list_collections() == []


class TestShowCommand:
    def test_show_nonexistent(self, store: RagStore):
        assert store.get_collection("nonexistent-handle") is None
