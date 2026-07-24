from __future__ import annotations

import json

from core.tree_search import (
    _build_flat_tree,
    _execute_list_children,
    _execute_read_node,
    _execute_search_keyword,
)


class FakeTreeNode:
    def __init__(self, id, node_id, parent_id, title, text="", summary="", start_index=0, end_index=0):
        self.id = id
        self.node_id = node_id
        self.parent_id = parent_id
        self.title = title
        self.text = text
        self.summary = summary
        self.start_index = start_index
        self.end_index = end_index


def _make_tree():
    return [
        FakeTreeNode(1, "0001", None, "Root Node", "Root summary"),
        FakeTreeNode(2, "0002", 1, "Child A", "Child A summary"),
        FakeTreeNode(3, "0003", 1, "Child B", "Child B summary"),
        FakeTreeNode(4, "0004", 2, "Grandchild A1", "Grandchild A1 summary"),
    ]


def test_build_flat_tree_structure():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    assert "0001" in tree_by_id
    assert "0002" in tree_by_id
    assert tree_by_id["0001"]["parent_node_id"] is None
    assert tree_by_id["0002"]["parent_node_id"] == "0001"
    assert "0002" in tree_by_id["0001"]["child_node_ids"]
    assert "0004" in tree_by_id["0002"]["child_node_ids"]


def test_list_children_root():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    result = json.loads(_execute_list_children("root", tree_by_id, nid_map))
    assert "children" in result
    assert len(result["children"]) == 1
    assert result["children"][0]["node_id"] == "0001"


def test_list_children_non_root():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    result = json.loads(_execute_list_children("0001", tree_by_id, nid_map))
    assert len(result["children"]) == 2
    titles = [c["title"] for c in result["children"]]
    assert "Child A" in titles
    assert "Child B" in titles


def test_list_children_not_found():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    result = json.loads(_execute_list_children("9999", tree_by_id, nid_map))
    assert "error" in result


def test_read_node_success():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    result = json.loads(_execute_read_node("0002", tree_by_id))
    assert result["node_id"] == "0002"
    assert result["title"] == "Child A"


def test_read_node_not_found():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    result = json.loads(_execute_read_node("9999", tree_by_id))
    assert "error" in result


def test_search_keyword_finds_match():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    result = json.loads(_execute_search_keyword("Grandchild", tree_by_id))
    assert len(result["matches"]) == 1
    assert result["matches"][0]["node_id"] == "0004"


def test_search_keyword_no_match():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    result = json.loads(_execute_search_keyword("nonexistent", tree_by_id))
    assert len(result["matches"]) == 0


def test_list_children_respects_reachable_ids():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    reachable = {"0001", "0003"}
    result = json.loads(_execute_list_children("0001", tree_by_id, nid_map, reachable))
    titles = [c["title"] for c in result["children"]]
    assert "Child B" in titles
    assert "Child A" not in titles


def test_read_node_respects_reachable_ids():
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)
    reachable = {"0001", "0003"}
    result = json.loads(_execute_read_node("0002", tree_by_id, reachable))
    assert "error" in result
    result = json.loads(_execute_read_node("0003", tree_by_id, reachable))
    assert result["node_id"] == "0003"
