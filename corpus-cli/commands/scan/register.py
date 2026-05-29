from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out

_DEFAULT_YOUTUBE_LIMIT = 50  # discovery limit per scan run


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command(
        "scan",
        help=(
            "Discover new items and add them to the sync pool.\n\n"
            "For 'youtube': queries the API/RSS for new videos and stages them.\n"
            "For 'obsidian': opens an interactive TUI to browse the vault and "
            "select files to include, remove, or exclude."
        ),
    )
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option(
        "--non-public",
        is_flag=True,
        default=False,
        help="YouTube: include non-public videos (private/unlisted/members-only) via API",
    )
    @click.option(
        "--use-api",
        is_flag=True,
        default=False,
        help="YouTube: force API mode instead of RSS",
    )
    @click.option(
        "--limit",
        "-l",
        type=int,
        default=None,
        help=f"Max new items to discover per source (YouTube default: {_DEFAULT_YOUTUBE_LIMIT})",
    )
    @click.option("--silent", "-s", is_flag=True, default=False)
    @click.option("--debug", is_flag=True, default=False)
    @click.pass_context
    def scan_cmd(ctx, source, non_public, use_api, limit, silent, debug, **kwargs):
        verbose = ctx.obj.get("verbose", True) and not silent
        _engine, plugins, store = build_engine(verbose)

        targets = list(plugins.keys()) if source == "all" else [source]

        for name in targets:
            plugin = plugins[name]
            if name == "youtube":
                _scan_youtube(plugin, store, non_public, use_api, limit, debug)
            elif name == "obsidian":
                _scan_obsidian(plugin, store)
            else:
                click.echo(f"scan: no discovery strategy for plugin '{name}'", err=True)

    return CommandManifest(name="scan", click_command=scan_cmd)


def _scan_youtube(plugin, store, non_public: bool, use_api: bool, limit: int | None, debug: bool) -> None:
    import inspect

    effective_limit = limit if limit is not None else _DEFAULT_YOUTUBE_LIMIT

    # Known = already indexed + already in pool (any status)
    indexed_ids = set(store.get_indexed_id_dates("youtube").keys())
    pool_ids = set(store.get_pool_ids("youtube").keys())
    known_id_dates = {sid: None for sid in (indexed_ids | pool_ids)}

    list_kwargs: dict = {
        "limit": effective_limit,
        "known_id_dates": known_id_dates,
    }
    sig = inspect.signature(plugin.list_items)
    if "use_api" in sig.parameters:
        list_kwargs["use_api"] = use_api or non_public
    if "non_public" in sig.parameters:
        list_kwargs["non_public"] = non_public
    if "debug" in sig.parameters:
        list_kwargs["debug"] = debug

    try:
        items = plugin.list_items(**list_kwargs)
    except RuntimeError as e:
        if "quota" in str(e).lower():
            raise click.ClickException(
                "YouTube API quota exceeded. Try again later or use RSS mode (no --use-api)."
            )
        raise

    added = store.add_to_pool(items, "youtube")
    pool_stats = store.pool_stats()
    yt_pool = next((p for p in pool_stats if p["source_plugin"] == "youtube"), {})
    pending = yt_pool.get("pending", 0)

    click.echo(
        f"youtube: discovered {len(items)} new video(s), "
        f"added {added} to pool  "
        f"[pool pending: {pending}]"
    )
    if len(items) == 0:
        click.echo("  → All known videos already in pool or indexed.")


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

    extra_excludes = set(
        (plugin._exclude_dirs if hasattr(plugin, "_exclude_dirs") else set())
    ) - {".obsidian", ".trash", ".git"}

    run_obsidian_scan_tui(vault, store, extra_exclude_dirs=extra_excludes or None)
