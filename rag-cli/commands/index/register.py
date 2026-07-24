from __future__ import annotations

import json
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out, resolve_provider_and_model
from core.collection_pointer import resolve_collection_name
from core.extractors import extract_local_file
from core.tree_builder import build_pdf_tree, build_md_tree, build_corpus_tree
from storage.models import SourceType, IndexRunStatus


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("index", help="Index a document into a collection.")
    @click.argument("path", required=False)
    @click.option("--collection", "-c", default=None, help="Target collection name.")
    @click.option("--tag", "-t", multiple=True, help="Sub-scope tag(s) of an already-indexed doc.")
    @click.option(
        "--mode",
        type=click.Choice(["new", "reindex"]),
        default="new",
        help="'new' (default): full index. 'reindex': regenerate summaries only.",
    )
    @click.option("--source", type=click.Choice(["local_file", "corpus"]), default="local_file")
    @click.option("--plugin", "plugin_name", default=None, help="Corpus plugin name.")
    @click.option("--handle", default=None, help="Corpus document handle.")
    @click.option("--sync-all", is_flag=True, default=False, help="Sync all corpus docs.")
    @click.option("--model", "-m", default=None, help="LLM model name.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.option("--provider", "-p", default=None, help="LLM provider name.")
    def index_cmd(path, collection, tag, mode, source, plugin_name, handle, sync_all, model, fmt, provider):
        collection_name = resolve_collection_name(collection)
        store, engine = get_rag_store()
        llm, model_name = resolve_provider_and_model(provider, model)

        coll = store.get_collection(collection_name)
        if not coll:
            raise click.ClickException(
                f"Collection {collection_name!r} not found. Run: rag collection create {collection_name}"
            )

        if source == "corpus":
            _index_corpus(store, engine, coll, llm, model_name, plugin_name, handle, sync_all, mode, fmt)
            return

        if not path:
            raise click.ClickException("PATH is required for local_file source.")
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise click.ClickException(f"File not found: {p}")

        _index_local_file(store, engine, coll, llm, model_name, p, mode, tag, fmt)

    return CommandManifest(name="index", click_command=index_cmd)


def _handle_for_path(path: Path) -> str:
    return f"local:{path.name}:{path.stat().st_size}"


def _index_local_file(store, engine, coll, llm, model_name, path, mode, tags, fmt):
    extracted = extract_local_file(path)
    handle = _handle_for_path(path)

    existing = store.get_document_by_handle(handle)
    if mode == "new" and existing and existing.content_hash == extracted.content_hash:
        out({"status": "skipped", "handle": handle, "reason": "unchanged"}, fmt)
        return

    from datetime import datetime, timezone

    doc = store.upsert_document(
        handle=handle,
        source_type=SourceType.local_file,
        source_ref=str(path),
        content_hash=extracted.content_hash,
        title=extracted.title,
    )

    run = store.create_index_run(doc.id, model_used=model_name or "", is_ephemeral=0)

    try:
        if path.suffix.lower() == ".pdf":
            pages = [(p.page_number, p.text) for p in extracted.pages]
            tree = build_pdf_tree(pages, provider=llm, model=model_name, summary_provider=llm)
        elif path.suffix.lower() in (".md", ".markdown"):
            tree = build_md_tree(extracted.full_text, summary_provider=llm, model=model_name)
        else:
            raise click.ClickException(f"Unsupported file type: {path.suffix}")

        tags_by_node = {}
        if tags:
            _assign_tags_recursive(tree, list(tags), tags_by_node)

        node_count = store.persist_tree(doc.id, tree, tags_by_node or None)
        store.add_collection_member(coll.id, doc.id)

        if tree:
            first_summary = tree[0].get("summary", "")
            store.upsert_document(
                handle=handle,
                source_type=SourceType.local_file,
                source_ref=str(path),
                content_hash=extracted.content_hash,
                title=extracted.title,
                description=first_summary,
            )

        store.finish_index_run(run.id, IndexRunStatus.success.value)
        out(
            {
                "status": "indexed",
                "handle": handle,
                "title": extracted.title,
                "collection": coll.name,
                "nodes": node_count,
                "mode": mode,
            },
            fmt,
        )
    except Exception as exc:
        store.finish_index_run(run.id, IndexRunStatus.failed.value, error=str(exc))
        raise


def _assign_tags_recursive(tree, tags, tags_by_node):
    for node in tree:
        node_id = node.get("node_id", "")
        title_lower = node.get("title", "").lower()
        for tag in tags:
            if tag.lower() in title_lower:
                if node_id not in tags_by_node:
                    tags_by_node[node_id] = []
                tags_by_node[node_id].append(tag)
        children = node.get("nodes", [])
        if children:
            _assign_tags_recursive(children, tags, tags_by_node)


def _index_corpus(store, engine, coll, llm, model_name, plugin_name, handle, sync_all, mode, fmt):
    raise click.ClickException(
        "Corpus source indexing requires direct database access. "
        "Use: rag index <path> for local files."
    )
