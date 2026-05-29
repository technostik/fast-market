from __future__ import annotations

import json
from pathlib import Path

import click
from fastapi import APIRouter

from commands.base import CommandManifest
from commands.helpers import build_engine


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command(
        "status",
        help="Show what has been indexed and what is left to sync, per source.",
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def status_cmd(ctx, fmt, **kwargs):
        _, _, store = build_engine(ctx.obj["verbose"])
        rows = store.full_status()
        if fmt == "json":
            click.echo(json.dumps(rows, ensure_ascii=False, default=str))
        else:
            _print_status(rows)

    return CommandManifest(
        name="status",
        click_command=status_cmd,
        api_router=_build_router(plugin_manifests),
    )


def _print_status(rows: list[dict]) -> None:
    if not rows:
        click.echo("No data yet. Run `corpus scan` to discover content.")
        return

    for row in rows:
        plugin   = row["source_plugin"]
        indexed  = row["indexed"]
        pool     = row["pool"]
        failures = row["failures"]

        pending   = pool.get("pending", 0)
        failed    = pool.get("failed", 0)
        excluded  = pool.get("excluded", 0)
        f_trans   = failures.get("transient", 0)
        f_perm    = failures.get("permanent", 0)

        click.echo(f"\n{plugin}")
        click.echo(f"  indexed    {indexed:>6} docs")
        click.echo( "  pool")

        if plugin == "youtube":
            pub    = pool.get("pending_public", 0)
            nonpub = pool.get("pending_nonpublic", 0)
            if pending:
                click.echo(
                    f"    pending  {pending:>6}  "
                    f"({pub} public · {nonpub} non-public)"
                )
            else:
                click.echo(f"    pending  {pending:>6}")
        else:
            click.echo(f"    pending  {pending:>6}")

        click.echo(f"    failed   {failed:>6}")
        click.echo(f"    excluded {excluded:>6}")

        if f_trans or f_perm:
            click.echo(f"  failures   {f_trans} transient · {f_perm} permanent")
        else:
            click.echo( "  failures        0")

    # ── Next-step hints ────────────────────────────────────────────────────
    hints: list[str] = []
    for row in rows:
        plugin = row["source_plugin"]
        pool   = row["pool"]
        pending = pool.get("pending", 0)
        failed  = pool.get("failed", 0)

        if plugin == "youtube":
            pub    = pool.get("pending_public", 0)
            nonpub = pool.get("pending_nonpublic", 0)
            if pub:
                hints.append(
                    f"  corpus sync --source youtube"
                    f"                  ({pub} public pending)"
                )
            if nonpub:
                hints.append(
                    f"  corpus sync --source youtube --non-public"
                    f"     ({nonpub} non-public pending)"
                )
            if failed:
                hints.append(
                    f"  corpus sync --source youtube --retry-failure"
                    f"  ({failed} failed)"
                )
        else:
            if pending:
                hints.append(
                    f"  corpus sync --source {plugin:<14}"
                    f"             ({pending} pending)"
                )
            if failed:
                hints.append(
                    f"  corpus sync --source {plugin:<14} --retry-failure"
                    f"  ({failed} failed)"
                )

    if hints:
        click.echo("\nNext:")
        for h in hints:
            click.echo(h)
    else:
        click.echo("\nNothing left to sync.")


def _build_router(plugin_manifests: dict) -> APIRouter:
    router = APIRouter()

    @router.get("/sources")
    def sources():
        from common.core.config import load_config
        from common.core.registry import build_plugins

        config = load_config()
        return list(
            build_plugins(config, tool_root=Path(__file__).resolve().parents[2]).keys()
        )

    @router.get("/items")
    def items(
        source: str | None = None,
        limit: int = 50,
        video_type: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        since: str | None = None,
        until: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
    ):
        from common.core.config import load_config
        from storage.sqlite_store import SQLiteStore, SearchFilters

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
        )
        return store.list_documents(source, limit, filters)

    @router.get("/status")
    def status():
        from common.core.config import load_config
        from storage.sqlite_store import SQLiteStore

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        return store.full_status()

    return router
