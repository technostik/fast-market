from __future__ import annotations

import click
from fastapi import APIRouter, Body, HTTPException

from commands.base import CommandManifest
from commands.helpers import build_engine, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("reindex")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def reindex_cmd(ctx, source, fmt, **kwargs):
        engine, plugins, _ = build_engine(ctx.obj["verbose"])
        targets = list(plugins.keys()) if source == "all" else [source]
        results = []
        for name in targets:
            result = engine.reindex(plugins[name])
            results.append({"source": result.source, "documents": result.documents, "chunks": result.chunks})
        out(results, fmt)

    return CommandManifest(
        name="reindex",
        click_command=reindex_cmd,
        api_router=_build_router(source_choices),
    )


def _build_router(source_choices: list[str]) -> APIRouter:
    router = APIRouter()

    @router.post("/reindex")
    def reindex(req: dict = Body(...)):
        source = req.get("source")
        from core.config import load_config
        from core.embedder import Embedder
        from core.registry import build_plugins
        from core.sync_engine import SyncEngine
        from storage.sqlite_store import SQLiteStore

        if source not in source_choices:
            raise HTTPException(status_code=400, detail="Unknown source")
        config = load_config()
        store = SQLiteStore(config.get("db_path", ":memory:"))
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
        engine = SyncEngine(store, embedder)
        plugins = build_plugins(config)
        result = engine.reindex(plugins[source])
        return {"source": result.source, "documents": result.documents, "chunks": result.chunks}

    return router
