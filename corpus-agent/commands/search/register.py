from __future__ import annotations

import click
from fastapi import APIRouter, HTTPException

from commands.base import CommandManifest
from commands.helpers import build_engine, fmt_duration, make_filters, out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command(
        "search",
        help="Search indexed documents using semantic (embedding-based) or keyword (FTS) matching.",
    )
    @click.argument("query")
    @click.option(
        "--mode", type=click.Choice(["semantic", "keyword"]), default="semantic"
    )
    @click.option("--limit", "-l", type=int, default=5)
    @click.option(
        "--source", type=click.Choice(list(plugin_manifests.keys())), default=None
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def search_cmd(ctx, query, mode, limit, source, fmt, **kwargs):
        engine, _, store = build_engine(ctx.obj["verbose"])
        filters = make_filters(source=source, **kwargs)
        if mode == "keyword":
            results = store.keyword_search(query, limit, filters)
        else:
            vector = engine.embedder.embed_texts([query])[0][1]
            results = store.semantic_search(vector, limit, filters)

        if fmt == "json":
            out(
                [
                    {
                        "handle": r.handle,
                        "source_plugin": r.source_plugin,
                        "source_id": r.source_id,
                        "title": r.title,
                        "score": round(r.score, 4),
                        "duration_seconds": r.duration_seconds,
                        "privacy_status": r.privacy_status,
                        "excerpt": r.excerpt,
                    }
                    for r in results
                ],
                fmt,
            )
        else:
            if not results:
                click.echo("no results")
                return
            for r in results:
                dur = (
                    f"  duration={fmt_duration(r.duration_seconds)}"
                    if r.duration_seconds
                    else ""
                )
                priv = f"  privacy={r.privacy_status}" if r.privacy_status else ""
                click.echo(f"[{r.handle}] {r.title}{dur}{priv}")
                click.echo(f"  score={round(r.score, 4)}  source={r.source_plugin}")
                click.echo(f"  {r.excerpt[:120]}")

    for pm in plugin_manifests.values():
        search_cmd.params.extend(pm.cli_options.get("search", []))

    return CommandManifest(
        name="search",
        click_command=search_cmd,
        api_router=_build_router(),
    )


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/search")
    def search(
        q: str,
        mode: str = "semantic",
        limit: int = 5,
        source: str | None = None,
        video_type: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        since: str | None = None,
        until: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        privacy_status: str | None = None,
    ):
        from common.core.config import load_config
        from core.embedder import Embedder
        from storage.sqlite_store import SQLiteStore, SearchFilters

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
        filters = SearchFilters(
            source=source,
            video_type=video_type,
            min_duration=min_duration,
            max_duration=max_duration,
            since=since,
            until=until,
            min_size=min_size,
            max_size=max_size,
            privacy_status=privacy_status,
        )
        if mode == "keyword":
            results = store.keyword_search(q, limit, filters)
        elif mode == "semantic":
            vector = embedder.embed_texts([q])[0][1]
            results = store.semantic_search(vector, limit, filters)
        else:
            raise HTTPException(status_code=400, detail="Invalid mode")
        return [
            {
                "handle": r.handle,
                "source_plugin": r.source_plugin,
                "source_id": r.source_id,
                "title": r.title,
                "excerpt": r.excerpt,
                "score": r.score,
                "duration_seconds": r.duration_seconds,
            }
            for r in results
        ]

    return router
