from __future__ import annotations

from pathlib import Path

import click
from fastapi import APIRouter, Body, HTTPException

from commands.base import CommandManifest
from commands.helpers import build_engine, out

_DEFAULT_LIMITS = {"youtube": 5}
_FALLBACK_LIMIT = 10


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("sync")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--mode", type=click.Choice(["new", "backfill"]), default="new")
    @click.option("--limit", type=int, default=None)
    @click.option("--clean", is_flag=True, default=False)
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def sync_cmd(ctx, source, mode, limit, clean, fmt, **kwargs):
        engine, plugins, store = build_engine(ctx.obj["verbose"])
        if clean:
            store.delete_all()
        targets = list(plugins.keys()) if source == "all" else [source]
        results = []
        for name in targets:
            effective_limit = limit if limit is not None else _DEFAULT_LIMITS.get(name, _FALLBACK_LIMIT)
            result = engine.sync(plugins[name], mode=mode, limit=effective_limit)
            results.append({
                "source": result.source,
                "indexed": result.indexed,
                "skipped": result.skipped,
                "failures": len(result.failures),
                "errors": [{"source_id": f.source_id, "error": f.error} for f in result.failures],
            })
        out(results, fmt)

    return CommandManifest(
        name="sync",
        click_command=sync_cmd,
        api_router=_build_router(source_choices),
    )


def _build_router(source_choices: list[str]) -> APIRouter:
    router = APIRouter()

    @router.post("/sync")
    def sync(req: dict = Body(...)):
        source = req.get("source")
        mode = req.get("mode", "new")
        limit = req.get("limit", 10)
        from common.core.config import load_config
        from core.embedder import Embedder
        from common.core.registry import build_plugins
        from core.sync_engine import SyncEngine
        from storage.sqlite_store import SQLiteStore

        if source not in source_choices:
            raise HTTPException(status_code=400, detail="Unknown source")
        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
        engine = SyncEngine(store, embedder)
        plugins = build_plugins(config, tool_root=Path(__file__).resolve().parents[2])
        result = engine.sync(plugins[source], mode=mode, limit=int(limit))
        return {
            "source": result.source,
            "indexed": result.indexed,
            "skipped": result.skipped,
            "failures": len(result.failures),
        }

    return router
