from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out, resolve_provider_and_model
from core.collection_pointer import resolve_collection_name
from core.tree_search import _build_flat_tree, run_agentic_search


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("ask", help="Ask a question about documents in a collection.")
    @click.argument("question")
    @click.option("--collection", "-c", default=None, help="Collection to query.")
    @click.option("--model", "-m", default=None, help="LLM model name.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.option("--provider", "-p", default=None, help="LLM provider name.")
    def ask_cmd(question, collection, model, fmt, provider):
        collection_name = resolve_collection_name(collection)
        store, _ = get_rag_store()
        llm, model_name = resolve_provider_and_model(provider, model)

        coll = store.get_collection(collection_name)
        if not coll:
            raise click.ClickException(f"Collection {collection_name!r} not found")

        root_entries = store.get_root_nodes_for_collection(coll.id)
        if not root_entries:
            raise click.ClickException(
                f"Collection {collection_name!r} has no documents. Run: rag index <path> --collection {collection_name}"
            )

        all_tree_by_id: dict[str, dict] = {}
        all_node_id_to_db_id: dict[str, int] = {}
        all_reachable_ids: set[str] = set()
        doc_summaries: list[str] = []

        for doc, root_node in root_entries:
            tree_nodes = store.get_tree_nodes_for_document(doc.id)
            tree_by_id, nid_map = _build_flat_tree(tree_nodes)
            reachable = store.get_reachable_node_ids(coll.id, doc.id)

            all_tree_by_id.update(tree_by_id)
            all_node_id_to_db_id.update(nid_map)
            all_reachable_ids.update(reachable)

            desc = doc.description or doc.title
            doc_summaries.append(f"- [{doc.handle}] {desc}")

        docs_overview = "\n".join(doc_summaries)
        system_prompt = (
            "You are a document analysis assistant. You have access to a collection of documents "
            "organized as hierarchical trees. Use list_children to navigate the tree, read_node to "
            "read content, and search_keyword to find specific topics.\n\n"
            "Always cite your source by including the document handle and node_id in your answer.\n\n"
            f"Documents in collection '{collection_name}':\n{docs_overview}"
        )

        answer = run_agentic_search(
            provider=llm,
            model=model_name,
            system_prompt=system_prompt,
            user_prompt=question,
            tree_by_id=all_tree_by_id,
            node_id_to_db_id=all_node_id_to_db_id,
            reachable_ids=all_reachable_ids,
        )

        out({"question": question, "collection": collection_name, "answer": answer}, fmt)

    return CommandManifest(name="ask", click_command=ask_cmd)
