from __future__ import annotations

import click
from fastapi import APIRouter, HTTPException, Query, Response

from commands.base import CommandManifest
from commands.helpers import build_engine, fmt_duration, make_filters, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.command("list")
    @click.option(
        "--limit",
        type=int,
        default=10,
        show_default=True,
        help="Number of items to return (use 1 for get-last behavior).",
    )
    @click.option(
        "--offset",
        type=int,
        default=0,
        show_default=True,
        help="Number of items to skip for pagination.",
    )
    @click.option("--source", type=click.Choice(source_choices), default=None, help="Filter by source plugin.")
    @click.option(
        "--order-by",
        type=click.Choice(["date", "size", "duration", "title"]),
        default="date",
        show_default=True,
        help="Sort field.",
    )
    @click.option("--reverse", is_flag=True, default=False, help="Reverse sort order.")
    @click.option("--format", "fmt", type=click.Choice(["json", "text", "table"]), default="text")
    @click.pass_context
    def list_cmd(ctx, limit, offset, source, order_by, reverse, fmt, **kwargs):
        """List indexed documents with filtering, sorting, and pagination."""
        if limit < 1:
            raise click.ClickException("--limit must be >= 1")
        if offset < 0:
            raise click.ClickException("--offset must be >= 0")

        _, _, store = build_engine(ctx.obj["verbose"])
        filters = make_filters(source=source, **kwargs)
        all_docs = store.list_documents_extended(
            source=source,
            filters=filters,
            order_by=order_by,
            reverse=reverse,
            limit=limit + offset,
        )
        docs = all_docs[offset : offset + limit]

        if not docs:
            click.echo("No documents found.", err=True)
            return

        if fmt == "json":
            out(docs, fmt)
        elif fmt == "table":
            _print_table(docs, source)
        else:
            _print_text(docs)

    for pm in plugin_manifests.values():
        seen = {tuple(param.opts) for param in list_cmd.params}
        for key in ("list", "search"):
            for option in pm.cli_options.get(key, []):
                sig = tuple(option.opts)
                if sig in seen:
                    continue
                list_cmd.params.append(option)
                seen.add(sig)

    return CommandManifest(
        name="list",
        click_command=list_cmd,
        api_router=_build_router(source_choices),
    )


def _print_text(docs: list[dict]) -> None:
    for doc in docs:
        plugin = doc["source_plugin"]
        title = doc["title"]
        handle = doc["handle"]
        date = doc.get("updated_at", "")[:10] if doc.get("updated_at") else ""

        meta_parts = [f"source={plugin}"]
        if date:
            meta_parts.append(f"date={date}")
        if doc.get("duration_seconds"):
            meta_parts.append(f"duration={fmt_duration(doc['duration_seconds'])}")
        if doc.get("privacy_status"):
            meta_parts.append(f"privacy={doc['privacy_status']}")
        if plugin == "obsidian":
            size = len(doc.get("raw_text", "") or "")
            meta_parts.append(f"size={size}chars")

        click.echo(f"[{handle}] {title}")
        click.echo(f"  {' · '.join(meta_parts)}")
        click.echo()


def _print_table(docs: list[dict], source: str | None) -> None:
    if not docs:
        return

    plugin = source or docs[0]["source_plugin"]

    if plugin == "youtube":
        click.echo(f"{'HANDLE':<25} {'TITLE':<40} {'DATE':<12} {'DURATION':<10} {'PRIVACY':<10}")
        click.echo("-" * 100)

        for doc in docs:
            handle = doc["handle"][:24]
            title = doc["title"][:39]
            date = doc.get("updated_at", "")[:10] if doc.get("updated_at") else ""
            dur = fmt_duration(doc.get("duration_seconds", 0)) or ""
            priv = (doc.get("privacy_status") or "")[:9]

            click.echo(f"{handle:<25} {title:<40} {date:<12} {dur:<10} {priv:<10}")
    elif plugin == "obsidian":
        click.echo(f"{'HANDLE':<25} {'TITLE':<40} {'DATE':<12} {'SIZE':<10}")
        click.echo("-" * 90)

        for doc in docs:
            handle = doc["handle"][:24]
            title = doc["title"][:39]
            date = doc.get("updated_at", "")[:10] if doc.get("updated_at") else ""
            size = len(doc.get("raw_text", "") or "")

            click.echo(f"{handle:<25} {title:<40} {date:<12} {size:<10}")
    else:
        click.echo(f"{'HANDLE':<25} {'TITLE':<40} {'SOURCE':<12} {'DATE':<12}")
        click.echo("-" * 92)

        for doc in docs:
            handle = doc["handle"][:24]
            title = doc["title"][:39]
            src = doc["source_plugin"][:11]
            date = doc.get("updated_at", "")[:10] if doc.get("updated_at") else ""

            click.echo(f"{handle:<25} {title:<40} {src:<12} {date:<12}")


def _build_router(source_choices: list[str]) -> APIRouter:
    router = APIRouter()

    @router.get("/list")
    def list_documents(
        limit: int = Query(10, ge=1, le=1000, description="Number of items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
        source: str | None = Query(None, description="Filter by source plugin"),
        order_by: str = Query("date", description="Sort field: date|size|duration|title"),
        reverse: bool = Query(False, description="Reverse sort order"),
        video_type: str | None = Query(None, description="YouTube: short|long"),
        min_duration: int | None = Query(None, ge=0, description="Min duration in seconds"),
        max_duration: int | None = Query(None, ge=0, description="Max duration in seconds"),
        privacy_status: str | None = Query(None, description="YouTube: public|private|unlisted|unknown"),
        since: str | None = Query(None, description="Filter by date: YYYY-MM-DD (inclusive)"),
        until: str | None = Query(None, description="Filter by date: YYYY-MM-DD (inclusive)"),
        min_size: int | None = Query(None, ge=0, description="Min content size in chars"),
        max_size: int | None = Query(None, ge=0, description="Max content size in chars"),
    ):
        from core.config import load_config
        from storage.sqlite_store import SQLiteStore, SearchFilters

        if source and source not in source_choices:
            raise HTTPException(status_code=400, detail=f"Unknown source: {source}")

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
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
        all_docs = store.list_documents_extended(
            source=source,
            filters=filters,
            order_by=order_by,
            reverse=reverse,
            limit=limit + offset + 100,
        )

        total = len(all_docs)
        docs = all_docs[offset : offset + limit]
        return Response(
            content=json.dumps(docs, default=str),
            media_type="application/json",
            headers={"X-Total-Count": str(total)},
        )

    return router
