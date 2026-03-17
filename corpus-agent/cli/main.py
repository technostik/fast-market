from __future__ import annotations

import json
import logging
import sys

import click
import structlog
import uvicorn

from core.config import load_config
from core.embedder import Embedder
from core.registry import build_plugins
from core.sync_engine import SyncEngine
from storage.sqlite_store import SQLiteStore, SearchFilters

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Verbose flag: when off, suppress all logs so only explicit output is printed
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.CRITICAL
    logging.basicConfig(level=level)
    # Silence the structlog shim
    logging.getLogger().setLevel(level)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(data: object, fmt: str) -> None:
    """Print data as JSON (fmt=json) or human-readable text (fmt=text)."""
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
    else:
        _print_text(data)


def _print_text(data: object) -> None:
    if isinstance(data, list):
        for item in data:
            _print_text(item)
            click.echo("")
    elif isinstance(data, dict):
        for k, v in data.items():
            if k == "raw_text":
                continue  # skip large field in default text view
            click.echo(f"  {k}: {v}")
    else:
        click.echo(str(data))


def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


# ---------------------------------------------------------------------------
# Engine builder
# ---------------------------------------------------------------------------

def _build(verbose: bool) -> tuple[SyncEngine, dict, SQLiteStore]:
    _configure_logging(verbose)
    config = load_config()
    store = SQLiteStore(config.get("db_path", ":memory:"))
    embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
    engine = SyncEngine(store, embedder)
    plugins = build_plugins(config)
    return engine, plugins, store


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show logs. When off, only result output is printed.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@main.command()
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Interactive setup wizard."""
    _configure_logging(ctx.obj["verbose"])
    from setup_wizard import run_wizard
    run_wizard()


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

@main.command()
@click.option("--source", type=click.Choice(["obsidian", "youtube", "all"]), default="all")
@click.option("--mode", type=click.Choice(["new", "backfill"]), default="new")
@click.option("--limit", type=int, default=None, help="Max items to sync (default: 10 obsidian, 5 youtube)")
@click.option("--clean", is_flag=True, default=False, help="Wipe all indexed data before syncing")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def sync(ctx: click.Context, source: str, mode: str, limit: int | None, clean: bool, fmt: str) -> None:
    """Sync content from sources into the index."""
    engine, plugins, store = _build(ctx.obj["verbose"])
    if clean:
        store.delete_all()

    targets = list(plugins.keys()) if source == "all" else [source]
    results = []

    for name in targets:
        effective_limit = limit if limit is not None else (5 if name == "youtube" else 10)
        result = engine.sync(plugins[name], mode=mode, limit=effective_limit)
        results.append({
            "source": result.source,
            "indexed": result.indexed,
            "skipped": result.skipped,
            "failures": len(result.failures),
            "errors": [{"source_id": f.source_id, "error": f.error} for f in result.failures],
        })

    _out(results if fmt == "json" else results, fmt)


# ---------------------------------------------------------------------------
# reindex
# ---------------------------------------------------------------------------

@main.command()
@click.option("--source", type=click.Choice(["obsidian", "youtube", "all"]), default="all")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def reindex(ctx: click.Context, source: str, fmt: str) -> None:
    """Rebuild embeddings for already-indexed documents."""
    engine, plugins, _ = _build(ctx.obj["verbose"])
    targets = list(plugins.keys()) if source == "all" else [source]
    results = []
    for name in targets:
        r = engine.reindex(plugins[name])
        results.append({"source": r.source, "documents": r.documents, "chunks": r.chunks})
    _out(results, fmt)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@main.command()
@click.argument("query")
@click.option("--mode", type=click.Choice(["semantic", "keyword"]), default="semantic")
@click.option("--limit", type=int, default=5)
@click.option("--source", type=click.Choice(["obsidian", "youtube"]), default=None, help="Filter by source plugin")
@click.option("--type", "video_type", type=click.Choice(["short", "long"]), default=None, help="YouTube only: short (≤60s) or long (>60s)")
@click.option("--min-duration", type=int, default=None, help="Min duration in seconds (YouTube)")
@click.option("--max-duration", type=int, default=None, help="Max duration in seconds (YouTube)")
@click.option("--since", default=None, help="Only results updated after this date (YYYY-MM-DD)")
@click.option("--until", default=None, help="Only results updated before this date (YYYY-MM-DD)")
@click.option("--min-size", type=int, default=None, help="Min content length in chars (Obsidian)")
@click.option("--max-size", type=int, default=None, help="Max content length in chars (Obsidian)")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    mode: str,
    limit: int,
    source: str | None,
    video_type: str | None,
    min_duration: int | None,
    max_duration: int | None,
    since: str | None,
    until: str | None,
    min_size: int | None,
    max_size: int | None,
    fmt: str,
) -> None:
    """Search the index. Returns handles, titles, and excerpts.

    \b
    Examples:
      corpus search "landing page tips" --source youtube --type long
      corpus search "obsidian setup" --source obsidian --min-size 500
      corpus search "API design" --mode keyword --format json
      corpus search "startup" --since 2024-01-01 --limit 10
    """
    engine, _, store = _build(ctx.obj["verbose"])

    filters = SearchFilters(
        source=source,
        min_duration=min_duration,
        max_duration=max_duration,
        video_type=video_type,
        since=since,
        until=until,
        min_size=min_size,
        max_size=max_size,
    )

    if mode == "keyword":
        results = store.keyword_search(query, limit, filters)
    else:
        vector = engine.embedder.embed_texts([query])[0][1]
        results = store.semantic_search(vector, limit, filters)

    if fmt == "json":
        _out([{
            "handle": r.handle,
            "source_plugin": r.source_plugin,
            "source_id": r.source_id,
            "title": r.title,
            "score": round(r.score, 4),
            "duration_seconds": r.duration_seconds,
            "excerpt": r.excerpt,
        } for r in results], fmt)
    else:
        if not results:
            click.echo("no results")
            return
        for r in results:
            dur = f"  duration={_fmt_duration(r.duration_seconds)}" if r.duration_seconds else ""
            click.echo(f"[{r.handle}] {r.title}{dur}")
            click.echo(f"  score={round(r.score, 4)}  source={r.source_plugin}")
            click.echo(f"  {r.excerpt[:120]}")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

@main.command(name="get")
@click.argument("handle")
@click.option("--what", type=click.Choice(["meta", "content", "all"]), default="meta",
              help="meta: fields only. content: raw_text only. all: everything.")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def get_doc(ctx: click.Context, handle: str, what: str, fmt: str) -> None:
    """Retrieve a document by handle or source_id.

    \b
    Examples:
      corpus get yt-my-video-a3f2
      corpus get yt-my-video-a3f2 --what content
      corpus get yt-my-video-a3f2 --what all --format json
      corpus get "Note.md" --what meta
    """
    _, _, store = _build(ctx.obj["verbose"])
    doc = store.get_document_by_handle(handle)
    if not doc:
        click.echo(f"not found: {handle}", err=True)
        sys.exit(1)

    if what == "content":
        click.echo(doc["raw_text"])
        return

    if what == "meta":
        meta_fields = {k: v for k, v in doc.items() if k != "raw_text"}
        _out(meta_fields, fmt)
        return

    # all
    if fmt == "json":
        _out(doc, fmt)
    else:
        for k, v in doc.items():
            if k == "raw_text":
                click.echo(f"\n--- content ({len(v)} chars) ---\n")
                click.echo(v)
            else:
                click.echo(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@main.command(name="delete")
@click.argument("handle")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def delete_doc(ctx: click.Context, handle: str, fmt: str) -> None:
    """Delete a document from the index by handle or source_id.

    \b
    Examples:
      corpus delete yt-my-video-a3f2
      corpus delete "Note.md"
    """
    _, _, store = _build(ctx.obj["verbose"])
    deleted = store.delete_document_by_handle(handle)
    if deleted:
        result = {"deleted": True, "handle": handle}
        _out(result, fmt)
    else:
        click.echo(f"not found: {handle}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
@click.pass_context
def status(ctx: click.Context, fmt: str) -> None:
    """Show document counts per source."""
    _, _, store = _build(ctx.obj["verbose"])
    rows = store.status()
    _out(rows, fmt)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@main.command()
@click.option("--port", type=int, default=8000)
@click.pass_context
def serve(ctx: click.Context, port: int) -> None:
    """Start the HTTP API and frontend."""
    _configure_logging(ctx.obj["verbose"])
    uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
