from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import get_rag_store, out, resolve_provider_and_model
from core.collection_pointer import resolve_collection_name
from core.extractors import extract_local_file, discover_files
from core.tree_builder import build_pdf_tree, build_md_tree
from storage.models import SourceType, IndexRunStatus


class IndexGroup(click.Group):
    """Click group that detects subcommands before Click tries to parse all options."""

    def parse_args(self, ctx, args):
        subcommand_names = self.list_commands(ctx)
        if args and args[0] in subcommand_names:
            ctx.invoked_subcommand = args[0]
            ctx.args = args[1:]
            ctx.params = {}
            return
        return super().parse_args(ctx, args)

    def invoke(self, ctx):
        if ctx.invoked_subcommand is not None:
            sub_cmd = self.get_command(ctx, ctx.invoked_subcommand)
            sub_ctx = sub_cmd.make_context(ctx.invoked_subcommand, list(ctx.args), parent=ctx)
            with sub_ctx:
                sub_cmd.invoke(sub_ctx)
        else:
            super().invoke(ctx)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("index", cls=IndexGroup, invoke_without_command=True, help="Index documents or manage index data.")
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
    @click.pass_context
    def index_group(ctx, path, collection, tag, mode, source, plugin_name, handle, sync_all, model, fmt, provider):
        if ctx.invoked_subcommand is not None:
            return

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
            raise click.ClickException(f"Path not found: {p}")

        if p.is_dir():
            files = discover_files(p)
            if not files:
                raise click.ClickException(f"No supported files found in {p}")
            _index_directory(store, engine, coll, llm, model_name, p, files, mode, tag, fmt)
        else:
            _index_local_file(store, engine, coll, llm, model_name, p, mode, tag, fmt)

    @index_group.command("cleanup", help="Drop and recreate all RAG index data.")
    @click.option("--all", "all_flag", is_flag=True, default=False, help="Clean all collections.")
    @click.option("--force", "-f", is_flag=True, default=False, help="Skip confirmation prompt.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    def cleanup_cmd(all_flag, force, fmt):
        store, engine = get_rag_store()

        stats = collect_stats(store, engine)

        if stats["total_docs"] == 0 and stats["total_nodes"] == 0 and stats["total_collections"] == 0:
            out({"status": "empty", "message": "Index is already clean. Nothing to delete."}, fmt)
            return

        summary = {
            "collections": stats["total_collections"],
            "documents": stats["total_docs"],
            "tree_nodes": stats["total_nodes"],
            "index_runs": stats["total_runs"],
            "collection_members": stats["total_members"],
        }

        if not force:
            click.echo("This will permanently delete the following:")
            click.echo(f"  Collections:      {summary['collections']}")
            click.echo(f"  Documents:        {summary['documents']}")
            click.echo(f"  Tree nodes:       {summary['tree_nodes']}")
            click.echo(f"  Index runs:       {summary['index_runs']}")
            click.echo(f"  Collection links: {summary['collection_members']}")
            click.echo()
            if not click.confirm("Proceed with cleanup?"):
                click.echo("Aborted.")
                return

        drop_and_recreate(engine)
        out({"status": "cleaned", **summary}, fmt)

    return CommandManifest(name="index", click_command=index_group)


def _handle_for_path(path: Path, base_dir: Path | None = None) -> str:
    if base_dir:
        rel = path.relative_to(base_dir)
        return f"local:{rel}:{path.stat().st_size}"
    return f"local:{path.name}:{path.stat().st_size}"


def collect_stats(store, engine):
    from storage.models import Base
    with engine.connect() as conn:
        return {
            "total_collections": len(conn.execute(Base.metadata.tables["collections"].select()).fetchall()),
            "total_docs": len(conn.execute(Base.metadata.tables["documents"].select()).fetchall()),
            "total_nodes": len(conn.execute(Base.metadata.tables["tree_nodes"].select()).fetchall()),
            "total_members": len(conn.execute(Base.metadata.tables["collection_members"].select()).fetchall()),
            "total_runs": len(conn.execute(Base.metadata.tables["index_runs"].select()).fetchall()),
        }


def drop_and_recreate(engine):
    from storage.models import Base
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _index_local_file(store, engine, coll, llm, model_name, path, mode, tags, fmt, base_dir=None):
    extracted = extract_local_file(path)
    handle = _handle_for_path(path, base_dir=base_dir)

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


def _index_directory(store, engine, coll, llm, model_name, base_dir, files, mode, tags, fmt):
    results = {"indexed": 0, "skipped": 0, "failed": 0, "errors": []}
    total = len(files)

    for i, f in enumerate(files, 1):
        rel = f.relative_to(base_dir)
        click.echo(f"[{i}/{total}] {rel}")

        try:
            _index_local_file(store, engine, coll, llm, model_name, f, mode, tags, fmt, base_dir=base_dir)
            results["indexed"] += 1
        except Exception as exc:
            results["failed"] += 1
            results["errors"].append({"file": str(rel), "error": str(exc)})
            click.echo(f"  FAILED: {exc}")

    out(
        {
            "status": "directory_indexed",
            "directory": str(base_dir),
            "total": total,
            "indexed": results["indexed"],
            "skipped": results["skipped"],
            "failed": results["failed"],
            "errors": results["errors"],
        },
        fmt,
    )


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
