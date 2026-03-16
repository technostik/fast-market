from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.embedder import Embedder
from storage.sqlite_store import SQLiteStore


class DummyEmbedder(Embedder):
    def _lazy_model(self):
        return self

    def encode(self, texts, batch_size=32):
        return [[float(len(t)), 1.0] for t in texts]


@pytest.fixture
def store() -> SQLiteStore:
    return SQLiteStore(":memory:")


@pytest.fixture
def embedder() -> DummyEmbedder:
    return DummyEmbedder()


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "data"
