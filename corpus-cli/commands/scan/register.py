from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_engine
from core.sync_errors import APIRateLimitError


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


def _scan_source(plugin, store, debug: bool):
    """Full-inventory scan for one plugin — shared with the webux /scan job.

    Business logic lives in core.scan.scan_source(); this command only formats
    the result. APIRateLimitError is converted to a clean click exception.
    """
    from core.scan import scan_source

    try:
        summary = scan_source(plugin, store, debug=debug)
    except APIRateLimitError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"{summary.source}: {summary.added} new · {summary.refreshed} metadata "
        f"refreshed ({summary.requeued} re-queued)  "
        f"[pool  pending={summary.pool_pending}  "
        f"synced={summary.pool_synced}  "
        f"failed={summary.pool_failed}  "
        f"excluded={summary.pool_excluded}]"
    )
    return summary


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