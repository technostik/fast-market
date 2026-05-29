from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out

# Scan always attempts to get the full channel inventory.
# The YouTube API caps at 10 pages × 100 videos = 1 000 videos per call.
_YT_SCAN_LIMIT = 9999  # effectively "all pages"


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command(
        "scan",
        help=(
            "Discover new items and add them to the sync pool.\n\n"
            "YouTube: fetches the full channel inventory via API and stores every "
            "video (public, private, unlisted, members-only) with its current privacy "
            "status. Re-running scan refreshes that status so videos that became public "
            "are automatically routed to the public sync path on the next 'corpus sync'.\n\n"
            "Obsidian: opens an interactive TUI to browse the vault and select "
            "files/folders to include, remove, or exclude."
        ),
    )
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--silent", "-s", is_flag=True, default=False)
    @click.option("--debug", is_flag=True, default=False)
    @click.pass_context
    def scan_cmd(ctx, source, silent, debug, **kwargs):
        verbose = ctx.obj.get("verbose", True) and not silent
        _engine, plugins, store = build_engine(verbose)

        targets = list(plugins.keys()) if source == "all" else [source]

        for name in targets:
            plugin = plugins[name]
            if name == "youtube":
                _scan_youtube(plugin, store, debug)
            elif name == "obsidian":
                _scan_obsidian(plugin, store)
            else:
                click.echo(f"scan: no discovery strategy for plugin '{name}'", err=True)

    return CommandManifest(name="scan", click_command=scan_cmd)


def _scan_youtube(plugin, store, debug: bool) -> None:
    """Full-channel scan: discovers new videos and refreshes privacy status of
    existing pending/failed pool items.

    Only synced/excluded IDs are passed as 'known' so the API returns fresh
    metadata for pending/failed items too — allowing detection of privacy changes.
    """
    import inspect
    from datetime import datetime

    # Load current pool and document state upfront
    all_pool = store.get_pool_items("youtube", status=None)
    pool_by_id: dict[str, dict] = {item["source_id"]: item for item in all_pool}
    indexed_ids: set[str] = set(store.get_indexed_id_dates("youtube").keys())

    # Pass synced/excluded/indexed IDs as "known" so the API skips them.
    # pending/failed IDs are NOT in known → the API returns them so we can
    # refresh their privacy status.
    skip_ids: set[str] = (
        {sid for sid, item in pool_by_id.items() if item["status"] in ("synced", "excluded")}
        | indexed_ids
    )
    known_id_dates = {sid: None for sid in skip_ids}

    list_kwargs: dict = {
        "limit": _YT_SCAN_LIMIT,
        "known_id_dates": known_id_dates,
        "scan_all": True,
        "debug": debug,
    }
    # scan_all is the new param; fall back gracefully if the plugin doesn't have it yet
    sig = inspect.signature(plugin.list_items)
    if "scan_all" not in sig.parameters:
        list_kwargs.pop("scan_all")

    try:
        items = plugin.list_items(**list_kwargs)
    except RuntimeError as e:
        if "quota" in str(e).lower():
            raise click.ClickException(
                "YouTube API quota exceeded. Try again later."
            )
        raise

    now = datetime.utcnow().isoformat()
    added = refreshed = requeued = 0

    for item in items:
        sid = item.source_id
        new_privacy = (item.metadata or {}).get("privacy_status", "unknown")

        if sid in pool_by_id:
            existing = pool_by_id[sid]
            old_privacy = (existing.get("metadata") or {}).get("privacy_status", "unknown")
            pool_status = existing["status"]

            if old_privacy != new_privacy:
                # Privacy changed — update metadata in pool
                store.upsert_pool_item(
                    "youtube", sid, pool_status,
                    _yt_meta(item),
                    added_at=existing["added_at"],
                )
                refreshed += 1
                # Re-queue failed items that are now public so the next sync
                # can fetch their transcript without API captions
                if new_privacy == "public" and pool_status == "failed":
                    store.mark_pool_item("youtube", sid, "pending")
                    requeued += 1
        elif sid not in indexed_ids:
            # Genuinely new video — not yet in pool or indexed
            store.upsert_pool_item("youtube", sid, "pending", _yt_meta(item), added_at=now)
            added += 1

    pool_stats = store.pool_stats()
    yt_pool = next((p for p in pool_stats if p["source_plugin"] == "youtube"), {})

    click.echo(
        f"youtube: {added} new · {refreshed} status refreshed "
        f"({requeued} re-queued public)  "
        f"[pool  pending={yt_pool.get('pending', 0)}  "
        f"synced={yt_pool.get('synced', 0)}  "
        f"failed={yt_pool.get('failed', 0)}]"
    )


def _yt_meta(item) -> dict:
    """Pool metadata for a YouTube ItemMeta — always includes updated_at so
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
