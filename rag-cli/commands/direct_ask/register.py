from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out, resolve_provider_and_model
from core.extractors import extract_local_file, discover_files
from core.tree_builder import build_pdf_tree, build_md_tree
from core.tree_search import _build_flat_tree, run_agentic_search
from storage.models import SourceType, IndexRunStatus


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("direct-ask", help="Ask a question about a file or directory without collection setup.")
    @click.argument("path")
    @click.argument("question")
    @click.option("--model", "-m", default=None, help="LLM model name.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.option("--keep", is_flag=True, default=False, help="Keep the document after answering.")
    @click.option("--provider", "-p", default=None, help="LLM provider name.")
    @click.option("--verbose", "-v", is_flag=True, default=False, help="Show agent tool call reflections.")
    def direct_ask_cmd(path, question, model, fmt, keep, provider, verbose):
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise click.ClickException(f"Path not found: {p}")

        store, engine = get_rag_store()
        llm, model_name = resolve_provider_and_model(provider, model)

        from common import structlog
        logger = structlog.get_logger(__name__)
        logger.info("direct_ask_started", path=str(p), keep=keep)

        if p.is_dir():
            files = discover_files(p)
            if not files:
                raise click.ClickException(f"No supported files found in {p}")
            _direct_ask_directory(store, llm, model_name, p, files, question, fmt, keep, verbose, logger)
        else:
            _direct_ask_single(store, llm, model_name, p, question, fmt, keep, verbose, logger)

    return CommandManifest(name="direct-ask", click_command=direct_ask_cmd)


def _build_index_file(path, store, llm, model_name, handle_prefix="direct"):
    extracted = extract_local_file(path)
    handle = f"{handle_prefix}:{path.name}:{path.stat().st_size}"

    doc = store.upsert_document(
        handle=handle,
        source_type=SourceType.local_file,
        source_ref=str(path),
        content_hash=extracted.content_hash,
        title=extracted.title,
    )

    run = store.create_index_run(doc.id, model_used=model_name or "", is_ephemeral=1)

    if path.suffix.lower() == ".pdf":
        pages = [(pg.page_number, pg.text) for pg in extracted.pages]
        tree = build_pdf_tree(pages, provider=llm, model=model_name, summary_provider=llm)
    elif path.suffix.lower() in (".md", ".markdown"):
        tree = build_md_tree(extracted.full_text, summary_provider=llm, model=model_name)
    else:
        raise click.ClickException(f"Unsupported file type: {path.suffix}")

    store.persist_tree(doc.id, tree)
    store.finish_index_run(run.id, IndexRunStatus.success.value)
    return doc, tree


def _verbose_tool_printer(tool_name, args, result):
    import json as _json
    click.echo(f"  [tool] {tool_name}({args})")
    try:
        parsed = _json.loads(result)
        summary = _json.dumps(parsed, ensure_ascii=False, indent=2)
        if len(summary) > 500:
            summary = summary[:500] + "\n  ..."
        click.echo(f"  [result] {summary}")
    except Exception:
        click.echo(f"  [result] {result[:500]}")


def _direct_ask_single(store, llm, model_name, p, question, fmt, keep, verbose, logger):
    doc = None
    try:
        doc, tree = _build_index_file(p, store, llm, model_name)
        logger.info("tree_built", nodes=len(tree))

        tree_nodes = store.get_tree_nodes_for_document(doc.id)
        tree_by_id, nid_map = _build_flat_tree(tree_nodes)

        system_prompt = f"Document: {doc.title}"
        on_tool_call = _verbose_tool_printer if verbose else None

        answer = run_agentic_search(
            provider=llm,
            model=model_name,
            system_prompt=system_prompt,
            user_prompt=question,
            tree_by_id=tree_by_id,
            node_id_to_db_id=nid_map,
            on_tool_call=on_tool_call,
        )

        out({"question": question, "document": doc.title, "answer": answer}, fmt)
    finally:
        if not keep and doc:
            store.purge_document(doc.id)
            logger.info("direct_ask_cleanup", handle=doc.handle)


def _direct_ask_directory(store, llm, model_name, base_dir, files, question, fmt, keep, verbose, logger):
    docs = []
    try:
        for i, f in enumerate(files, 1):
            rel = f.relative_to(base_dir)
            click.echo(f"[{i}/{len(files)}] Indexing {rel}")
            try:
                doc, tree = _build_index_file(f, store, llm, model_name, handle_prefix="direct")
                docs.append(doc)
                logger.info("tree_built", file=str(rel), nodes=len(tree))
            except Exception as exc:
                click.echo(f"  FAILED: {exc}")

        if not docs:
            raise click.ClickException("No documents could be indexed.")

        all_tree_by_id = {}
        all_nid_map = {}
        doc_titles = []
        for idx, doc in enumerate(docs):
            prefix = f"doc{idx}_"
            tree_nodes = store.get_tree_nodes_for_document(doc.id)
            tree_by_id, nid_map = _build_flat_tree(tree_nodes, node_id_prefix=prefix)
            all_tree_by_id.update(tree_by_id)
            all_nid_map.update(nid_map)
            doc_titles.append(doc.title)

        system_prompt = f"Documents ({len(docs)} files): {', '.join(doc_titles)}"
        on_tool_call = _verbose_tool_printer if verbose else None

        answer = run_agentic_search(
            provider=llm,
            model=model_name,
            system_prompt=system_prompt,
            user_prompt=question,
            tree_by_id=all_tree_by_id,
            node_id_to_db_id=all_nid_map,
            on_tool_call=on_tool_call,
        )

        out(
            {
                "question": question,
                "documents": doc_titles,
                "answer": answer,
            },
            fmt,
        )
    finally:
        if not keep:
            for doc in docs:
                store.purge_document(doc.id)
                logger.info("direct_ask_cleanup", handle=doc.handle)
