from __future__ import annotations

from core.embedder import Embedder


def test_hash_stable():
    assert Embedder.hash_text("x") == Embedder.hash_text("x")
