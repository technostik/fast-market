from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out


def _render_tree(tree: list[dict], indent: int = 0) -> str:
    lines = []
    for node in tree:
        prefix = "  " * indent
        nid = node.get("node_id", "?")
        title = node.get("title", "")
        summary = node.get("summary", "")
        summary_str = f"  -- {summary[:60]}..." if summary else ""
        lines.append(f"{prefix}[{nid}] {title}{summary_str}")
        children = node.get("nodes", [])
        if children:
            lines.append(_render_tree(children, indent + 1))
    return "\n".join(lines)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("show", help="Show document details and tree structure.")
    @click.argument("handle")
    @click.option("--tree", "show_tree", is_flag=True, default=False, help="Render ASCII tree.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def show_cmd(handle, show_tree, fmt):
        store, _ = get_rag_store()
        doc = store.get_document_by_handle(handle)
        if not doc:
            raise click.ClickException(f"Document {handle!r} not found")

        tree_nodes = store.get_tree_nodes_for_document(doc.id)

        if not show_tree:
            result = {
                "handle": doc.handle,
                "title": doc.title,
                "description": doc.description,
                "source_type": doc.source_type.value,
                "created_at": doc.created_at,
                "node_count": len(tree_nodes),
            }
            out(result, fmt)
            return

        from core.tree_search import _build_flat_tree
        tree_by_id, _ = _build_flat_tree(tree_nodes)

        root_nodes = [
            tree_by_id[tn.node_id]
            for tn in tree_nodes
            if tn.parent_id is None
        ]
        root_dicts = []
        for rn in root_nodes:
            d = {
                "node_id": rn["node_id"],
                "title": rn["title"],
                "summary": rn.get("summary", ""),
                "nodes": [],
            }
            root_dicts.append(d)
            _attach_children(d, rn, tree_by_id)

        if fmt == "json":
            out(root_dicts, fmt)
        else:
            click.echo(_render_tree(root_dicts))

    return CommandManifest(name="show", click_command=show_cmd)


def _attach_children(parent_dict: dict, parent_data: dict, tree_by_id: dict) -> None:
    for child_nid in parent_data.get("child_node_ids", []):
        child_data = tree_by_id.get(child_nid)
        if not child_data:
            continue
        child_dict = {
            "node_id": child_data["node_id"],
            "title": child_data["title"],
            "summary": child_data.get("summary", ""),
            "nodes": [],
        }
        parent_dict["nodes"].append(child_dict)
        _attach_children(child_dict, child_data, tree_by_id)
