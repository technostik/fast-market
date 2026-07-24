from __future__ import annotations

import json
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out, resolve_provider_and_model
from core.extractors import extract_local_file
from core.tree_builder import build_pdf_tree, build_md_tree
from core.tree_search import _build_flat_tree, run_agentic_search
from storage.models import SourceType, IndexRunStatus


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("direct-ask", help="Ask a question about a single file without collection setup.")
    @click.argument("path")
    @click.argument("question")
    @click.option("--model", "-m", default=None, help="LLM model name.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.option("--keep", is_flag=True, default=False, help="Keep the document after answering.")
    @click.option("--provider", "-p", default=None, help="LLM provider name.")
    def direct_ask_cmd(path, question, model, fmt, keep, provider):
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise click.ClickException(f"File not found: {p}")

        store, engine = get_rag_store()
        llm, model_name = resolve_provider_and_model(provider, model)

        from common import structlog
        logger = structlog.get_logger(__name__)
        logger.info("direct_ask_started", path=str(p), keep=keep)

        extracted = extract_local_file(p)
        handle = f"direct:{p.name}:{p.stat().st_size}"

        doc = store.upsert_document(
            handle=handle,
            source_type=SourceType.local_file,
            source_ref=str(p),
            content_hash=extracted.content_hash,
            title=extracted.title,
        )

        run = store.create_index_run(doc.id, model_used=model_name or "", is_ephemeral=1)

        try:
            if p.suffix.lower() == ".pdf":
                pages = [(pg.page_number, pg.text) for pg in extracted.pages]
                tree = build_pdf_tree(pages, provider=llm, model=model_name, summary_provider=llm)
            elif p.suffix.lower() in (".md", ".markdown"):
                tree = build_md_tree(extracted.full_text, summary_provider=llm, model=model_name)
            else:
                raise click.ClickException(f"Unsupported file type: {p.suffix}")

            store.persist_tree(doc.id, tree)
            store.finish_index_run(run.id, IndexRunStatus.success.value)
            logger.info("tree_built", nodes=len(tree))

            tree_nodes = store.get_tree_nodes_for_document(doc.id)
            tree_by_id, nid_map = _build_flat_tree(tree_nodes)

            system_prompt = (
                "You are a document analysis assistant. You have access to a single document "
                "organized as a hierarchical tree. Use list_children to navigate, read_node to "
                "read content, and search_keyword to find topics.\n\n"
                f"Document: {extracted.title}\n"
            )

            answer = run_agentic_search(
                provider=llm,
                model=model_name,
                system_prompt=system_prompt,
                user_prompt=question,
                tree_by_id=tree_by_id,
                node_id_to_db_id=nid_map,
            )

            out({"question": question, "document": extracted.title, "answer": answer}, fmt)

        except Exception as exc:
            store.finish_index_run(run.id, IndexRunStatus.failed.value, error=str(exc))
            raise
        finally:
            if not keep:
                store.purge_document(doc.id)
                logger.info("direct_ask_cleanup", handle=handle)

    return CommandManifest(name="direct-ask", click_command=direct_ask_cmd)
