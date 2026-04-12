from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import click

from commands.snapshot_service import (
    SOURCE_CONFIG,
    _get_config_source,
    do_snapshot,
    do_restore,
    do_rollback,
    show_status,
    list_snapshots,
)


def _clean_bak_files(root: Path, dry_run: bool = False) -> list[Path]:
    """Recursively find and optionally remove *.bak* files under root."""
    bak_files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            if fnmatch.fnmatch(fname, "*.bak*"):
                bak_files.append(Path(dirpath) / fname)

    for f in bak_files:
        if dry_run:
            click.echo(f"[DRY RUN] Would remove: {f}")
        else:
            f.unlink()
            click.echo(f"Removed: {f}")

    return bak_files


def register():
    @click.group("config", invoke_without_command=True)
    @click.pass_context
    def config_cmd(ctx):
        """Manage XDG config snapshot/restore.

        Snapshots ~/.config/fast-market by copying files to a safe location,
        allowing safe config changes with restore.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(config_status)

    @config_cmd.command("snapshot")
    @click.option(
        "--target", "-t",
        "targets",
        multiple=True,
        help="Specific files/dirs to snapshot (default: entire directory)",
    )
    def config_snapshot(targets):
        """Snapshot ~/.config/fast-market config files."""
        source = _get_config_source()
        if not source.exists():
            click.echo(f"Config directory does not exist: {source}")
            return
        target_list = list(targets) if targets else ["."]
        do_snapshot(SOURCE_CONFIG, source, target_list, flat_only=False, sentinel_prefix="fast-market")

    @config_cmd.command("restore")
    def config_restore():
        """Restore ~/.config/fast-market, moving files back."""
        source = _get_config_source()
        source.mkdir(parents=True, exist_ok=True)
        do_restore(SOURCE_CONFIG, source, flat_only=False)

    @config_cmd.command("status")
    def config_status():
        """Show snapshot status of ~/.config/fast-market."""
        source = _get_config_source()
        show_status(SOURCE_CONFIG, source, flat_only=False)

    @config_cmd.command("list")
    def config_list():
        """List all snapshots."""
        list_snapshots(SOURCE_CONFIG, sentinel_prefix="fast-market")

    @config_cmd.command("rollback")
    @click.argument("snapshot_name", required=False)
    def config_rollback(snapshot_name):
        """Rollback to a specific snapshot or the current one."""
        source = _get_config_source()
        source.mkdir(parents=True, exist_ok=True)
        do_rollback(SOURCE_CONFIG, source, snapshot_name, flat_only=False, re_snap=False)

    @config_cmd.command("clean-bak")
    @click.option("--dry-run", "-n", is_flag=True, help="Show what would be removed without deleting")
    def config_clean_bak(dry_run):
        """Remove all *.bak* files recursively from XDG config directory."""
        source = _get_config_source()
        if not source.exists():
            click.echo(f"Config directory does not exist: {source}")
            return
        bak_files = _clean_bak_files(source, dry_run=dry_run)
        if not dry_run:
            click.echo(f"\nRemoved {len(bak_files)} .bak file(s).")
        else:
            click.echo(f"\nWould remove {len(bak_files)} .bak file(s).")

    return config_cmd
