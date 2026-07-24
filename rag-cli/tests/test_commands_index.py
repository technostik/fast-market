from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.store import RagStore, create_memory_engine, make_session_factory
from core.tree_builder import build_md_tree


@pytest.fixture
def store():
    engine = create_memory_engine()
    sf = make_session_factory(engine)
    return RagStore(sf)


@pytest.fixture
def runner():
    return CliRunner()


def test_build_md_tree_fixture(sample_md_content):
    tree = build_md_tree(sample_md_content)
    assert len(tree) == 1
    assert tree[0]["title"] == "Sample Document"
    child_titles = [c["title"] for c in tree[0]["nodes"]]
    assert "Chapter 1: Introduction" in child_titles
    assert "Chapter 2: Methods" in child_titles
    assert "Chapter 3: Results" in child_titles
    assert "Chapter 4: Conclusion" in child_titles


def test_tree_has_correct_depth(sample_md_content):
    tree = build_md_tree(sample_md_content)
    assert len(tree) == 1
    sample_doc = tree[0]
    chapters = sample_doc["nodes"]
    assert len(chapters) == 4
    intro = [n for n in chapters if n["title"] == "Chapter 1: Introduction"][0]
    assert len(intro.get("nodes", [])) == 2
    child_titles = [c["title"] for c in intro["nodes"]]
    assert "Section 1.1: Background" in child_titles
    assert "Section 1.2: Goals" in child_titles
