from __future__ import annotations

import click
from pydantic import BaseModel

from commands.base import CommandManifest
from commands.helpers import _TOOL_ROOT, build_engine, build_operations, out
from core.sync_errors import APIRateLimitError

# Per-source limit defaults for pool-based sync.
# 0 means no limit (fetch all pending).
_DEFAULT_LIMITS: dict[str, int] = {
    "youtube": 10,
    "obsidian": 0,
}
_FALLBACK_LIMIT = 10


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command(
        "sync",
        help=(
            "Fetch and index pending items from the pool.\n\n"
            "Run 'corpus scan' first to populate the pool with items to sync.\n\n"
            "Use --mode reindex or --mode backfill to bypass the pool and operate "
            "directly on the store."
        ),
    )
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option(
        "--mode",
        type=click.Choice(["new", "backfill", "reindex"]),
        default="new",
        help=(
            "'new' (default): fetch pending pool items. "
            "'backfill': re-fetch all known IDs bypassing the pool. "
            "'reindex': regenerate embeddings for already-stored documents."
        ),
    )
    @click.option(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Max items to process per source (YouTube default: 10, Obsidian default: all).",
    )
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
        help="Also clear permanent failures (requires --retry-failure)",
    )
    @click.option(
        "--include-blocked",
        is_flag=True,
        default=False,
        help="Also clear blocked entries (requires --retry-failure)",
    )
    @click.option("--silent", "-s", is_flag=True, default=False)
    @click.option("--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.option("--debug", is_flag=True, default=False)
    @click.option(
        "--field",
        "field_name",
        default=None,
        help=(
            "Fill a declared soft field on documents missing it (e.g. --field summary). "
            "Uses the registered operation that produces that field."
        ),
    )
    @click.option(
        "--handles",
        "handles",
        multiple=True,
        default=None,
        help="Restrict --field sync to specific document handles (repeatable).",
    )
    @click.option(
        "--non-public",
        is_flag=True,
        default=False,
        help=(
            "Sync non-public videos (private/unlisted/members-only) using YouTube API captions. "
            "Without this flag only public videos are processed (RSS/transcript-api)."
        ),
    )
    # Legacy: kept for backfill bypass path only
    @click.option("--use-api", is_flag=True, default=False, hidden=True)
    @click.pass_context
    def sync_cmd(
        ctx,
        source,
        mode,
        limit,
        retry_failure,
        clear_permanent,
        include_blocked,
        silent,
        fmt,
        debug,
        use_api,
        non_public,
        field_name,
        handles,
        **kwargs,
    ):
        import sys
        from common.core.config import load_config

        verbose = ctx.obj.get("verbose", True) and not silent
        engine, plugins, store = build_engine(verbose)
        config = load_config()
        obsidian_vault_path = config.get("obsidian", {}).get("vault_path")

        targets = list(plugins.keys()) if source == "all" else [source]

        if field_name:
            has_warning = _sync_field_cmd(
                engine, store, config, targets, field_name, handles,
                limit, obsidian_vault_path, fmt, verbose,
            )
            if has_warning:
                ctx.exit(1)
            return

        results = []
        has_warning = False

        for name in targets:
            plugin = plugins[name]

            if retry_failure:
                cleared = store.clear_failures(
                    name,
                    include_permanent=clear_permanent,
                    include_blocked=include_blocked,
                )
                if cleared > 0 and verbose:
                    click.echo(f"Cleared {cleared} failure(s) for {name}")
                # Re-queue failed pool items so they get a fresh attempt
                failed_pool = store.get_pool_items(plugin_name=name, status="failed")
                for item in failed_pool:
                    store.mark_pool_item(name, item["source_id"], "pending")

            if mode == "reindex":
                reindex_result = engine.reindex(plugin)
                results.append(
                    {
                        "source": reindex_result.source,
                        "documents": reindex_result.documents,
                        "chunks": reindex_result.chunks,
                    }
                )
                continue

            if mode == "backfill":
                # Bypass pool: re-fetch all known documents
                vault_path = obsidian_vault_path if name == "obsidian" else None
                effective_use_api = use_api or (non_public and name == "youtube")
                try:
                    result = engine.sync(
                        plugin,
                        mode="backfill",
                        limit=limit or _DEFAULT_LIMITS.get(name, _FALLBACK_LIMIT) or 9999,
                        vault_path=vault_path,
                        use_api=effective_use_api,
                        non_public=non_public if name == "youtube" else False,
                        debug=debug,
                    )
                except APIRateLimitError as e:
                    raise click.ClickException(str(e)) from e
                result_dict = _result_to_dict(result)
                if result.warning:
                    has_warning = True
                results.append(result_dict)
                continue

            # mode == "new": consume pending pool items
            effective_limit = limit if limit is not None else _DEFAULT_LIMITS.get(name)

            # For YouTube the privacy filter runs in Python (privacy_status lives in
            # metadata_json, not a first-class column), so we must fetch all pending
            # items first and apply the limit only after filtering.
            db_limit = None if name == "youtube" else (effective_limit or None)
            pool_items = store.get_pool_items(
                plugin_name=name,
                status="pending",
                limit=db_limit,
            )

            # YouTube: route public vs non-public to different transcript methods.
            # Public videos use RSS/youtube-transcript-api (no API quota for fetching).
            # Non-public videos require YouTube API captions (needs OAuth).
            if name == "youtube":
                if non_public:
                    pool_items = [
                        i for i in pool_items
                        if (i.get("metadata") or {}).get("privacy_status", "unknown") != "public"
                    ]
                else:
                    pool_items = [
                        i for i in pool_items
                        if (i.get("metadata") or {}).get("privacy_status", "public") == "public"
                    ]
                if effective_limit:
                    pool_items = pool_items[:effective_limit]

            if not pool_items:
                # No pending pool items: fall back to a direct incremental sync
                # so `corpus sync` keeps working without a prior `corpus scan`.
                # Pool-based workflows still take precedence when the pool has
                # items waiting.
                vault_path = obsidian_vault_path if name == "obsidian" else None
                effective_use_api = use_api or (non_public and name == "youtube")
                try:
                    result = engine.sync(
                        plugin,
                        mode="new",
                        limit=limit or _DEFAULT_LIMITS.get(name, _FALLBACK_LIMIT) or 9999,
                        vault_path=vault_path,
                        use_api=effective_use_api,
                        non_public=non_public if name == "youtube" else False,
                        debug=debug,
                    )
                except APIRateLimitError as e:
                    raise click.ClickException(str(e)) from e
                result_dict = _result_to_dict(result)
                if result.warning:
                    has_warning = True
                results.append(result_dict)
                continue

            vault_path = obsidian_vault_path if name == "obsidian" else None
            result = engine.sync_pool_items(plugin, pool_items, vault_path=vault_path)
            result_dict = _result_to_dict(result)
            if result.warning:
                has_warning = True
            results.append(result_dict)

        out(results, fmt)

        # Repair suggestions for any remaining failures
        for name in targets:
            failures = store.list_failures(name)
            if not failures:
                continue
            transient = sum(1 for f in failures if f.get("error_type") == "transient")
            permanent = sum(1 for f in failures if f.get("error_type") == "permanent")
            blocked = sum(
                1 for f in failures if "blocked" in f.get("error_message", "").lower()
            )
            if transient:
                click.echo(
                    f"\nRun `corpus sync --source {name} --retry-failure` "
                    f"to retry {transient} transient failure(s)"
                )
            if permanent:
                click.echo(
                    f"Run `corpus sync --source {name} --retry-failure --clear-permanent` "
                    f"to retry {permanent} permanent failure(s)"
                )
            if blocked:
                click.echo(
                    f"Run `corpus sync --source {name} --retry-failure --include-blocked` "
                    f"to retry {blocked} blocked item(s)"
                )

        if has_warning:
            ctx.exit(1)

    return CommandManifest(name="sync", click_command=sync_cmd, api_router=_build_router())


class _SyncRequest(BaseModel):
    source: str
    mode: str = "new"
    limit: int | None = None
    retry_failure: bool = False
    clear_permanent: bool = False
    non_public: bool = False


def _build_router():
    from fastapi import APIRouter, HTTPException

    router = APIRouter()

    @router.post("/sync")
    def sync(req: _SyncRequest):
        from common.core.config import load_config
        from common.core.registry import build_plugins
        from core.embedder import Embedder
        from core.sync_engine import SyncEngine
        from storage.sqlite_store import SQLiteStore

        config = load_config()
        plugins = build_plugins(config, tool_root=_TOOL_ROOT)
        if req.source not in plugins:
            raise HTTPException(
                status_code=400, detail=f"Unknown source plugin: {req.source}"
            )

        store = SQLiteStore(config.get("db_path"))
        embedder = Embedder(batch_size=int(config.get("embed_batch_size", 32)))
        engine = SyncEngine(store, embedder)
        plugin = plugins[req.source]

        if req.retry_failure:
            store.clear_failures(
                req.source, include_permanent=req.clear_permanent
            )

        if req.mode == "reindex":
            result = engine.reindex(plugin)
            return {
                "source": result.source,
                "documents": result.documents,
                "chunks": result.chunks,
            }

        vault_path = (
            config.get("obsidian", {}).get("vault_path")
            if req.source == "obsidian"
            else None
        )
        try:
            result = engine.sync(
                plugin,
                mode=req.mode,
                limit=req.limit or _DEFAULT_LIMITS.get(req.source, _FALLBACK_LIMIT) or 9999,
                vault_path=vault_path,
                use_api=req.non_public,
                non_public=req.non_public,
                debug=False,
            )
        except APIRateLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return _result_to_dict(result)

    return router


def _result_to_dict(result) -> dict:
    d: dict = {
        "source": result.source,
        "indexed": result.indexed,
        "skipped": result.skipped,
        "failures": len(result.failures),
        "errors": [{"source_id": f.source_id, "error": f.error} for f in result.failures],
    }
    if result.warning:
        d["warning"] = result.warning
    return d


def _sync_field_cmd(
    engine, store, config, targets, field_name, handles, limit,
    obsidian_vault_path, fmt, verbose,
) -> bool:
    """--field path: fill a declared soft field on documents missing it.
    Returns True when any source produced a warning."""
    import click

    operations = build_operations(config)
    matches = [m for m in operations.values() if m.field == field_name]
    if not matches:
        available = sorted({m.field for m in operations.values() if m.field})
        raise click.ClickException(
            f"No registered operation produces field '{field_name}'. "
            f"Available fields: {', '.join(available) or 'none'}."
        )
    if len(matches) > 1:
        raise click.ClickException(
            f"Multiple operations produce field '{field_name}': "
            f"{', '.join(m.name for m in matches)}. Use a more specific field."
        )
    manifest = matches[0]

    if not store.get_field_definition(field_name):
        raise click.ClickException(
            f"Field '{field_name}' is not defined. Declare it with "
            f"`corpus field create --name {field_name}`."
        )

    results = []
    has_warning = False
    for name in targets:
        operation = manifest.operation_class(config)
        if operation.applies_to not in ("all", name):
            results.append(
                {
                    "source": name,
                    "indexed": 0,
                    "skipped": 0,
                    "failures": 0,
                    "errors": [
                        {
                            "source_id": "-",
                            "error": (
                                f"Operation '{operation.name}' applies to "
                                f"'{operation.applies_to}', not '{name}'."
                            ),
                        }
                    ],
                    "warning": (
                        f"Operation '{operation.name}' does not apply to source '{name}'."
                    ),
                }
            )
            has_warning = True
            continue
        vault_path = obsidian_vault_path if name == "obsidian" else None
        result = engine.sync_field(
            field_name,
            operation,
            source=name,
            limit=limit or 1000,
            handles=list(handles) or None,
            vault_path=vault_path,
        )
        result_dict = _result_to_dict(result)
        if result.warning:
            has_warning = True
        results.append(result_dict)

    out(results, fmt)
    return has_warning
