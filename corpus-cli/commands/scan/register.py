from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out
from core.sync_errors import APIRateLimitError

# Scan always attempts to get the full inventory.
# YouTube API caps at 10 pages × 100 videos = 1 000 videos per call.
_SCAN_LIMIT = 9999  # effectively "all pages"


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command(
        "scan",
        help=(
            "Discover new items and add them to the sync pool.\n\n"
            "Plugins with a full-inventory discovery path (scan_all) are walked "
            "generically: every item is added to the pool with its current "
            "metadata. Re-running scan refreshes that metadata so e.g. YouTube "
            "videos that became public are automatically routed to the public "
            "sync path on the next 'corpus sync'.\n\n"
            "Obsidian: opens an interactive TUI to browse the vault and select "
            "files/folders to include, remove, or exclude."
        ),
    )
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--silent", "-s", is_flag=True, default=False)
    @click.option("--debug", is_flag=True, default=False)
    @click.option(
        "--auto",
        is_flag=True,
        default=False,
        help=(
            "Non-interactive: use the generic full-inventory scan for every "
            "source, skipping the interactive Obsidian TUI."
        ),
    )
    @click.pass_context
    def scan_cmd(ctx, source, silent, debug, auto, **kwargs):
        verbose = ctx.obj.get("verbose", True) and not silent
        _engine, plugins, store = build_engine(verbose)

        targets = list(plugins.keys()) if source == "all" else [source]

        for name in targets:
            plugin = plugins[name]
            strategy = getattr(plugin, "scan_strategy", "generic")
            if strategy == "tui" and not auto:
                _scan_obsidian(plugin, store)
            else:
                _scan_source(plugin, store, debug)

    return CommandManifest(name="scan", click_command=scan_cmd)


def _scan_source(plugin, store, debug: bool) -> None:
    """Generic full-inventory scan for any plugin whose list_items supports
    scan_all=True.

    Adds genuinely new items to the pool as 'pending' and refreshes the pool
    metadata of existing pending/failed items so status changes are detected.
    Synced/excluded/indexed IDs are passed as 'known' so the plugin skips them.

    Plugins that re-queue on a state change (e.g. YouTube: a 'failed' item that
    became 'public' is reset to 'pending') can declare `requeue_on` describing
    the new-state value; defaults to nothing.
    """
    import inspect
    from datetime import datetime

    # Load current pool and document state upfront
    all_pool = store.get_pool_items(plugin.name, status=None)
    pool_by_id: dict[str, dict] = {item["source_id"]: item for item in all_pool}
    indexed_ids: set[str] = set(store.get_indexed_id_dates(plugin.name).keys())

    # Pass synced/excluded/indexed IDs as "known" so the API skips them.
    # pending/failed IDs are NOT in known → the API returns them so we can
    # refresh their metadata.
    skip_ids: set[str] = (
        {sid for sid, item in pool_by_id.items() if item["status"] in ("synced", "excluded")}
        | indexed_ids
    )
    known_id_dates = {sid: None for sid in skip_ids}

    list_kwargs: dict = {
        "limit": _SCAN_LIMIT,
        "known_id_dates": known_id_dates,
        "scan_all": True,
        "debug": debug,
    }
    # scan_all is the new param; fall back gracefully if the plugin doesn't have it yet
    sig = inspect.signature(plugin.list_items)
    if "scan_all" not in sig.parameters:
        raise click.ClickException(
            f"scan: plugin '{plugin.name}' has no scan_all discovery path"
        )

    try:
        items = plugin.list_items(**list_kwargs)
    except APIRateLimitError as e:
        raise click.ClickException(str(e)) from e

    now = datetime.utcnow().isoformat()
    added = refreshed = requeued = 0

    # Plugin hook: which metadata state change re-queues a failed pool item.
    requeue_on = getattr(plugin, "requeue_on", None)

    for item in items:
        sid = item.source_id
        new_meta = _item_meta(item)

        if sid in pool_by_id:
            existing = pool_by_id[sid]
            pool_status = existing["status"]

            if existing.get("metadata") != new_meta:
                # Metadata changed — update metadata in pool
                store.upsert_pool_item(
                    plugin.name, sid, pool_status,
                    new_meta,
                    added_at=existing["added_at"],
                )
                refreshed += 1
                # Re-queue failed items whose state changed to the requeue-on
                # state (e.g. YouTube: failed → now public → pending).
                if pool_status == "failed" and requeue_on and new_meta.get(
                    "privacy_status"
                ) == requeue_on:
                    store.mark_pool_item(plugin.name, sid, "pending")
                    requeued += 1
        elif sid not in indexed_ids:
            # Genuinely new item — not yet in pool or indexed
            store.upsert_pool_item(plugin.name, sid, "pending", new_meta, added_at=now)
            added += 1

    pool_stats = store.pool_stats()
    src_pool = next((p for p in pool_stats if p["source_plugin"] == plugin.name), {})

    click.echo(
        f"{plugin.name}: {added} new · {refreshed} metadata refreshed "
        f"({requeued} re-queued)  "
        f"[pool  pending={src_pool.get('pending', 0)}  "
        f"synced={src_pool.get('synced', 0)}  "
        f"failed={src_pool.get('failed', 0)}]"
    )


def _item_meta(item) -> dict:
    """Pool metadata for an ItemMeta — always includes updated_at so
    sync_pool_items can reconstruct the publication date from the pool."""
    meta = dict(item.metadata or {})
    if item.updated_at and "updated_at" not in meta:
        meta["updated_at"] = item.updated_at.isoformat()
    return meta


def _scan_obsidian(plugin, store) -> None:
    from common.core.config import load_config
    from pathlib import Path

    config = load_config()
    vault_path_str = config.get("obsidian", {}).get("vault_path")
    if not vault_path_str:
        raise click.ClickException("Missing obsidian.vault_path in config.")

    vault = Path(str(vault_path_str)).expanduser()
    if not vault.exists():
        raise click.ClickException(f"Obsidian vault not found: {vault}")

    from commands.scan.obsidian_tui import run_obsidian_scan_tui

    extra_excludes = (
        set(plugin._exclude_dirs) - {".obsidian", ".trash", ".git"}
        if hasattr(plugin, "_exclude_dirs")
        else None
    )
    run_obsidian_scan_tui(vault, store, extra_exclude_dirs=extra_excludes or None)
