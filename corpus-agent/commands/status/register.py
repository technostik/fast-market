from __future__ import annotations

from pathlib import Path

import click
from fastapi import APIRouter

from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("status")
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def status_cmd(ctx, fmt, **kwargs):
        _, _, store = build_engine(ctx.obj["verbose"])
        out(store.status(), fmt)

    return CommandManifest(
        name="status",
        click_command=status_cmd,
        api_router=_build_router(plugin_manifests),
    )


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

    return router
