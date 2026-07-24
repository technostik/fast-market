from __future__ import annotations

from core.tree_builder import (
    build_md_tree,
    extract_md_nodes,
    _assign_text_to_nodes,
    _build_tree_from_md_nodes,
    _clean_tree_for_output,
)


def test_extract_md_nodes_finds_headings(sample_md_content: str):
    node_list, lines = extract_md_nodes(sample_md_content)
    titles = [n["node_title"] for n in node_list]
    assert "Chapter 1: Introduction" in titles
    assert "Chapter 2: Methods" in titles
    assert "Chapter 3: Results" in titles
    assert "Chapter 4: Conclusion" in titles


def test_extract_md_nodes_finds_subheadings(sample_md_content: str):
    node_list, _ = extract_md_nodes(sample_md_content)
    titles = [n["node_title"] for n in node_list]
    assert "Section 1.1: Background" in titles
    assert "Section 1.2: Goals" in titles
    assert "Section 3.1: Key Findings" in titles
    assert "Section 3.2: Limitations" in titles


def test_build_tree_from_md_nodes_produces_hierarchy(sample_md_content: str):
    node_list, lines = extract_md_nodes(sample_md_content)
    nodes_with_text = _assign_text_to_nodes(node_list, lines)
    tree = _build_tree_from_md_nodes(nodes_with_text)
    assert len(tree) > 0
    root_titles = [n["title"] for n in tree]
    assert "Sample Document" in root_titles


def test_build_tree_has_node_ids(sample_md_content: str):
    tree = build_md_tree(sample_md_content)
    for node in tree:
        assert "node_id" in node
        assert len(node["node_id"]) == 4


def test_build_tree_children_have_text(sample_md_content: str):
    tree = build_md_tree(sample_md_content)
    for node in tree:
        children = node.get("nodes", [])
        for child in children:
            assert "text" in child
            assert len(child["text"]) > 0


def test_clean_tree_for_output_removes_text_if_desired(sample_md_content: str):
    node_list, lines = extract_md_nodes(sample_md_content)
    nodes_with_text = _assign_text_to_nodes(node_list, lines)
    tree = _build_tree_from_md_nodes(nodes_with_text)
    cleaned = _clean_tree_for_output(tree)
    for node in cleaned:
        assert "text" in node
        children = node.get("nodes", [])
        for child in children:
            assert "text" in child


def test_build_md_tree_without_summary(sample_md_content: str):
    tree = build_md_tree(sample_md_content)
    assert len(tree) > 0
    for node in tree:
        assert "summary" not in node or isinstance(node.get("summary"), str)
