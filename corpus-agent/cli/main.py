from __future__ import annotations

import click
import structlog
import uvicorn

from core.config import load_config
from core.embedder import Embedder
from core.registry import build_plugins
from core.sync_engine import SyncEngine
from storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)


def build_engine() -> tuple[SyncEngine, dict[str, object], SQLiteStore]:
    config = load_config()
    store = SQLiteStore(config.get("db_path", ":memory:"))
    embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
    engine = SyncEngine(store, embedder)
    plugins = build_plugins(config)
    return engine, plugins, store


@click.group()
def main() -> None:
    pass


@main.command()
def setup() -> None:
    from setup_wizard import run_wizard
    run_wizard()


@main.command()
@click.option("--source", type=click.Choice(["obsidian", "youtube", "all"]), default="all")
@click.option("--mode", type=click.Choice(["new", "backfill"]), default="new")
@click.option("--limit", type=int, default=None, help="Max items to sync (default: 10 obsidian, 5 youtube)")
@click.option("--clean", is_flag=True, default=False, help="Wipe all indexed data before syncing")
def sync(source: str, mode: str, limit: int | None, clean: bool) -> None:
    engine, plugins, store = build_engine()

    if clean:
        store.delete_all()
        logger.info("store_wiped")

    targets = list(plugins.keys()) if source == "all" else [source]

    for name in targets:
        # Per-source sensible defaults
        effective_limit = limit if limit is not None else (5 if name == "youtube" else 10)
        result = engine.sync(plugins[name], mode=mode, limit=effective_limit)
        logger.info(
            "sync_done",
            source=name,
            indexed=result.indexed,
            skipped=result.skipped,
            failures=len(result.failures),
        )
        for failure in result.failures:
            logger.error("sync_failure", source=name, source_id=failure.source_id, error=failure.error)


@main.command()
@click.option("--source", type=click.Choice(["obsidian", "youtube", "all"]), default="all")
def reindex(source: str) -> None:
    engine, plugins, _ = build_engine()
    targets = list(plugins.keys()) if source == "all" else [source]
    for name in targets:
        result = engine.reindex(plugins[name])
        logger.info("reindex_done", source=name, documents=result.documents, chunks=result.chunks)


@main.command()
@click.argument("query")
@click.option("--mode", type=click.Choice(["semantic", "keyword"]), default="semantic")
@click.option("--limit", type=int, default=5)
def search(query: str, mode: str, limit: int) -> None:
    engine, _, store = build_engine()
    if mode == "keyword":
        results = store.keyword_search(query, limit)
    else:
        vector = engine.embedder.embed_texts([query])[0][1]
        results = store.semantic_search(vector, limit)
    for res in results:
        logger.info(
            "search_result",
            source=res.source_plugin,
            source_id=res.source_id,
            title=res.title,
            score=round(res.score, 4),
        )


@main.command()
def status() -> None:
    _, _, store = build_engine()
    for row in store.status():
        logger.info("status", **row)


@main.command()
@click.option("--port", type=int, default=8000)
def serve(port: int) -> None:
    uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
