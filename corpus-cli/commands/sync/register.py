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

    @click.command(
        "sync",
        help="Fetch content from configured sources and index it into the corpus.",
    )
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option(
        "--mode",
        type=click.Choice(["new", "backfill", "reindex"]),
        default="new",
        help=(
            "Sync mode: 'new' sync only new items, "
            "'backfill' re-fetch all items, "
            "'reindex' regenerate embeddings for existing documents"
        ),
    )
    @click.option("--limit", "-l", type=int, default=None)
    @click.option("--clean", is_flag=True, default=False)
    @click.option(
        "--retry-failure",
        is_flag=True,
        default=False,
        help="Clear tracked failures before syncing",
    )
    @click.option(
        "--clear-permanent",
        is_flag=True,
        default=False,
        help="Also retry permanent failures (requires --retry-failure)",
    )
    @click.option(
        "--include-blocked",
        is_flag=True,
        default=False,
        help="Also retry blocked videos (requires --retry-failure)",
    )
    @click.option(
        "--silent", "-s", is_flag=True, default=False, help="Suppress detailed logs"
    )
    @click.option(
        "--use-api",
        is_flag=True,
        default=False,
        help="Use YouTube API instead of RSS (for full channel sync)",
    )
    @click.option(
        "--non-public",
        is_flag=True,
        default=False,
        help="Sync non-public videos (private/unlisted/members-only) via API",
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def sync_cmd(
        ctx,
        source,
        mode,
        limit,
        clean,
        silent,
        use_api,
        non_public,
        fmt,
        retry_failure,
        clear_permanent,
        include_blocked,
        **kwargs,
    ):
        import sys

        from common.core.config import load_config

        verbose = ctx.obj.get("verbose", True) and not silent
        engine, plugins, store = build_engine(verbose)
        config = load_config()
        obsidian_vault_path = config.get("obsidian", {}).get("vault_path")
        if clean:
            store.delete_all()
        targets = list(plugins.keys()) if source == "all" else [source]
        results = []
        has_warning = False
        for name in targets:
            cleared = 0
            if retry_failure:
                cleared = store.clear_failures(
                    name,
                    include_permanent=clear_permanent,
                    include_blocked=include_blocked,
                )
                if cleared > 0 and verbose:
                    click.echo(f"Cleared {cleared} failure(s) for {name}")

            if mode == "reindex":
                reindex_result = engine.reindex(plugins[name])
                result_dict = {
                    "source": reindex_result.source,
                    "documents": reindex_result.documents,
                    "chunks": reindex_result.chunks,
                }
            else:
                effective_limit = (
                    limit
                    if limit is not None
                    else _DEFAULT_LIMITS.get(name, _FALLBACK_LIMIT)
                )
                vault_path = obsidian_vault_path if name == "obsidian" else None
                result = engine.sync(
                    plugins[name],
                    mode=mode,
                    limit=effective_limit,
                    vault_path=vault_path,
                    use_api=use_api if name == "youtube" else False,
                    non_public=non_public if name == "youtube" else False,
                )
                result_dict = {
                    "source": result.source,
                    "indexed": result.indexed,
                    "skipped": result.skipped,
                    "failures": len(result.failures),
                    "errors": [
                        {"source_id": f.source_id, "error": f.error}
                        for f in result.failures
                    ],
                }
                if retry_failure:
                    result_dict["cleared_failures"] = cleared
                if result.warning:
                    result_dict["warning"] = result.warning
                    has_warning = True
            results.append(result_dict)

        out(results, fmt)

        # Show repair suggestions if there were failures
        for name in targets:
            failures = store.list_failures(name)
            if failures:
                transient = sum(
                    1 for f in failures if f.get("error_type") == "transient"
                )
                permanent = sum(
                    1 for f in failures if f.get("error_type") == "permanent"
                )

                if transient > 0:
                    click.echo(
                        f"\nRun `corpus sync --source {name} --retry-failure` to retry {transient} transient failure(s)"
                    )
                if permanent > 0:
                    click.echo(
                        f"Run `corpus sync --source {name} --retry-failure --clear-permanent` to retry {permanent} permanent failure(s)"
                    )
                # Check for blocked (error message contains "blocked" or "BLOCKED")
                blocked = sum(
                    1
                    for f in failures
                    if "blocked" in f.get("error_message", "").lower()
                )
                if blocked > 0:
                    click.echo(
                        f"Run `corpus sync --source {name} --retry-failure --include-blocked` to retry {blocked} blocked video(s)"
                    )

        if has_warning:
            ctx.exit(1)

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
        obsidian_vault_path = config.get("obsidian", {}).get("vault_path")
        vault_path = obsidian_vault_path if source == "obsidian" else None

        if mode == "reindex":
            reindex_result = engine.reindex(plugins[source])
            return {
                "source": reindex_result.source,
                "documents": reindex_result.documents,
                "chunks": reindex_result.chunks,
            }

        result = engine.sync(
            plugins[source], mode=mode, limit=int(limit), vault_path=vault_path
        )
        return {
            "source": result.source,
            "indexed": result.indexed,
            "skipped": result.skipped,
            "failures": len(result.failures),
        }

    return router
