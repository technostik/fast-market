from __future__ import annotations

from core.tree_search import _build_flat_tree, run_agentic_search
from common.llm.base import LLMProvider, LLMRequest, LLMResponse, ToolCall


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self):
        self._call_count = 0
        self._responses = []
        self._calls = []

    def add_response(self, content="", tool_calls=None):
        self._responses.append((content, tool_calls or []))

    def _complete_raw(self, request: LLMRequest) -> LLMResponse:
        self._calls.append(request)
        if self._call_count < len(self._responses):
            content, tool_calls = self._responses[self._call_count]
            self._call_count += 1
            return LLMResponse(
                content=content,
                model="fake",
                tool_calls=tool_calls,
            )
        self._call_count += 1
        return LLMResponse(content="Done.", model="fake")

    def list_models(self):
        return ["fake"]


class FakeTreeNode:
    def __init__(self, id, node_id, parent_id, title, summary="", start_index=0, end_index=0):
        self.id = id
        self.node_id = node_id
        self.parent_id = parent_id
        self.title = title
        self.summary = summary
        self.start_index = start_index
        self.end_index = end_index


def _make_tree():
    return [
        FakeTreeNode(1, "0001", None, "Root", "Root summary"),
        FakeTreeNode(2, "0002", 1, "Child A", "Child A summary"),
        FakeTreeNode(3, "0003", 1, "Child B", "Child B summary"),
    ]


def test_run_agentic_search_direct_answer():
    provider = FakeProvider()
    provider.add_response(content="The answer is 42.")
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)

    answer = run_agentic_search(
        provider=provider,
        model=None,
        system_prompt="You are a helpful assistant.",
        user_prompt="What is the answer?",
        tree_by_id=tree_by_id,
        node_id_to_db_id=nid_map,
        max_iterations=3,
    )
    assert answer == "The answer is 42."
    assert len(provider._calls) == 1


def test_run_agentic_search_with_tool_call():
    provider = FakeProvider()
    tc = ToolCall(
        id="call-1",
        name="list_children",
        arguments={"node_id": "root"},
    )
    provider.add_response(content="", tool_calls=[tc])
    provider.add_response(content="I found the relevant section.")
    tree_nodes = _make_tree()
    tree_by_id, nid_map = _build_flat_tree(tree_nodes)

    answer = run_agentic_search(
        provider=provider,
        model=None,
        system_prompt="Navigate the tree.",
        user_prompt="Find something.",
        tree_by_id=tree_by_id,
        node_id_to_db_id=nid_map,
        max_iterations=5,
    )
    assert answer == "I found the relevant section."
    assert len(provider._calls) == 2
