from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out

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
    # Legacy options kept for backfill/reindex bypass path
    @click.option("--use-api", is_flag=True, default=False, hidden=True)
    @click.option("--non-public", is_flag=True, default=False, hidden=True)
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
        **kwargs,
    ):
        import sys
        from common.core.config import load_config

        verbose = ctx.obj.get("verbose", True) and not silent
        engine, plugins, store = build_engine(verbose)
        config = load_config()
        obsidian_vault_path = config.get("obsidian", {}).get("vault_path")

        targets = list(plugins.keys()) if source == "all" else [source]
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
                except RuntimeError as e:
                    if "quota" in str(e).lower():
                        raise click.ClickException(
                            "YouTube API quota exceeded. Try again later."
                        )
                    raise
                result_dict = _result_to_dict(result)
                if result.warning:
                    has_warning = True
                results.append(result_dict)
                continue

            # mode == "new": consume pending pool items
            effective_limit = limit if limit is not None else _DEFAULT_LIMITS.get(name)
            pool_items = store.get_pool_items(
                plugin_name=name,
                status="pending",
                limit=effective_limit or None,
            )

            if not pool_items:
                results.append(
                    {
                        "source": name,
                        "indexed": 0,
                        "skipped": 0,
                        "failures": 0,
                        "errors": [],
                        "warning": "No pending items in pool. Run `corpus scan` first.",
                    }
                )
                has_warning = True
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

    return CommandManifest(name="sync", click_command=sync_cmd)


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
