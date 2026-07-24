from __future__ import annotations

import json

from common import structlog
from common.llm.base import LLMRequest, LLMProvider, ToolCall

logger = structlog.get_logger(__name__)


def _build_list_children_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "list_children",
            "description": (
                "List the direct children of a tree node, showing title and summary. "
                "Use this to navigate the document hierarchy and find the right section."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "The node_id to list children of. Use 'root' for the document root.",
                    }
                },
                "required": ["node_id"],
            },
        },
    }


def _build_read_node_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "read_node",
            "description": (
                "Read the full text content of a specific tree node. "
                "Use this to get the actual content after navigating with list_children."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "The node_id to read.",
                    }
                },
                "required": ["node_id"],
            },
        },
    }


def _build_search_keyword_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "search_keyword",
            "description": (
                "Search for keywords in the document tree. "
                "Returns matching node_ids and titles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for.",
                    }
                },
                "required": ["query"],
            },
        },
    }


def _execute_list_children(
    node_id: str,
    tree_by_id: dict[str, dict],
    node_id_to_db_id: dict[str, int],
    reachable_ids: set[str] | None = None,
) -> str:
    if node_id == "root":
        root_nodes = [
            n for n in tree_by_id.values()
            if n.get("parent_node_id") is None
        ]
        children = root_nodes
    else:
        node = tree_by_id.get(node_id)
        if not node:
            return json.dumps({"error": f"Node {node_id!r} not found"})
        child_ids = node.get("child_node_ids", [])
        children = [tree_by_id[cid] for cid in child_ids if cid in tree_by_id]

    if reachable_ids is not None:
        children = [c for c in children if c["node_id"] in reachable_ids]

    result = []
    for child in children:
        entry = {
            "node_id": child["node_id"],
            "title": child.get("title", ""),
            "summary": child.get("summary", "")[:300],
        }
        child_count = len(child.get("child_node_ids", []))
        if child_count > 0:
            entry["child_count"] = child_count
        result.append(entry)

    return json.dumps({"children": result}, ensure_ascii=False)


def _execute_read_node(
    node_id: str,
    tree_by_id: dict[str, dict],
    reachable_ids: set[str] | None = None,
) -> str:
    node = tree_by_id.get(node_id)
    if not node:
        return json.dumps({"error": f"Node {node_id!r} not found"})
    if reachable_ids is not None and node_id not in reachable_ids:
        return json.dumps({"error": f"Node {node_id!r} not accessible in this collection scope"})

    return json.dumps(
        {
            "node_id": node["node_id"],
            "title": node.get("title", ""),
            "text": node.get("text", ""),
            "summary": node.get("summary", ""),
            "start_index": node.get("start_index"),
            "end_index": node.get("end_index"),
        },
        ensure_ascii=False,
    )


def _execute_search_keyword(
    query: str,
    tree_by_id: dict[str, dict],
    reachable_ids: set[str] | None = None,
) -> str:
    query_lower = query.lower()
    matches = []
    for node_id, node in tree_by_id.items():
        if reachable_ids is not None and node_id not in reachable_ids:
            continue
        title = node.get("title", "").lower()
        text = node.get("text", "").lower()
        summary = node.get("summary", "").lower()
        if query_lower in title or query_lower in text or query_lower in summary:
            matches.append(
                {
                    "node_id": node_id,
                    "title": node.get("title", ""),
                    "summary": node.get("summary", "")[:200],
                }
            )
    return json.dumps({"matches": matches[:20]}, ensure_ascii=False)


def _build_flat_tree(
    tree_nodes: list,
) -> tuple[dict[str, dict], dict[str, int]]:
    tree_by_id: dict[str, dict] = {}
    node_id_to_db_id: dict[str, int] = {}

    for tn in tree_nodes:
        node_data = {
            "db_id": tn.id,
            "node_id": tn.node_id,
            "title": tn.title,
            "text": "",
            "summary": tn.summary,
            "start_index": tn.start_index,
            "end_index": tn.end_index,
            "parent_node_id": None,
            "child_node_ids": [],
        }
        tree_by_id[tn.node_id] = node_data
        node_id_to_db_id[tn.node_id] = tn.id

    for tn in tree_nodes:
        if tn.parent_id:
            for nid, data in tree_by_id.items():
                if data["db_id"] == tn.parent_id:
                    tree_by_id[tn.node_id]["parent_node_id"] = nid
                    data["child_node_ids"].append(tn.node_id)
                    break

    return tree_by_id, node_id_to_db_id


def run_agentic_search(
    provider: LLMProvider,
    model: str | None,
    system_prompt: str,
    user_prompt: str,
    tree_by_id: dict[str, dict],
    node_id_to_db_id: dict[str, int],
    reachable_ids: set[str] | None = None,
    max_iterations: int = 15,
) -> str:
    tools = [
        _build_list_children_tool(),
        _build_read_node_tool(),
        _build_search_keyword_tool(),
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for iteration in range(max_iterations):
        request = LLMRequest(
            messages=messages,
            model=model,
            temperature=0.3,
            max_tokens=4096,
            tools=tools,
        )
        response = provider.complete(request)

        if response.tool_calls:
            for tc in response.tool_calls:
                logger.info("ask_tool_call", tool=tc.name, node_id=tc.arguments.get("node_id", tc.arguments.get("query", "")))
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                        ],
                    }
                )

                if tc.name == "list_children":
                    result = _execute_list_children(
                        tc.arguments.get("node_id", "root"),
                        tree_by_id,
                        node_id_to_db_id,
                        reachable_ids,
                    )
                elif tc.name == "read_node":
                    result = _execute_read_node(
                        tc.arguments.get("node_id", ""),
                        tree_by_id,
                        reachable_ids,
                    )
                elif tc.name == "search_keyword":
                    result = _execute_search_keyword(
                        tc.arguments.get("query", ""),
                        tree_by_id,
                        reachable_ids,
                    )
                else:
                    result = json.dumps({"error": f"Unknown tool: {tc.name}"})

                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
        else:
            return response.content or ""

    return "Reached maximum iterations without a final answer."
