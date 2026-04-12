from __future__ import annotations

from pathlib import Path

import click

from commands.snapshot_service import (
    SOURCE_DATA,
    _get_data_source,
    do_snapshot,
    do_restore,
    do_rollback,
    show_status,
    list_snapshots,
)


def register():
    @click.group("data", invoke_without_command=True)
    @click.pass_context
    def data_cmd(ctx):
        """Manage XDG data snapshot/restore.

        Snapshots ~/.local/share/fast-market by copying files to a safe location,
        allowing safe data changes with restore.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(data_status)

    @data_cmd.command("snapshot")
    @click.option(
        "--target", "-t",
        "targets",
        multiple=True,
        help="Specific files/dirs to snapshot (default: entire directory)",
    )
    def data_snapshot(targets):
        """Snapshot ~/.local/share/fast-market data files."""
        source = _get_data_source()
        if not source.exists():
            click.echo(f"Data directory does not exist: {source}")
            return
        target_list = list(targets) if targets else ["."]
        do_snapshot(SOURCE_DATA, source, target_list, flat_only=False, sentinel_prefix="data")

    @data_cmd.command("restore")
    def data_restore():
        """Restore ~/.local/share/fast-market, moving files back."""
        source = _get_data_source()
        source.mkdir(parents=True, exist_ok=True)
        do_restore(SOURCE_DATA, source, flat_only=False)

    @data_cmd.command("status")
    def data_status():
        """Show snapshot status of ~/.local/share/fast-market."""
        source = _get_data_source()
        show_status(SOURCE_DATA, source, flat_only=False)

    @data_cmd.command("list")
    def data_list():
        """List all snapshots."""
        list_snapshots(SOURCE_DATA, sentinel_prefix="data")

    @data_cmd.command("rollback")
    @click.argument("snapshot_name", required=False)
    def data_rollback(snapshot_name):
        """Rollback to a specific snapshot or the current one."""
        source = _get_data_source()
        source.mkdir(parents=True, exist_ok=True)
        do_rollback(SOURCE_DATA, source, snapshot_name, flat_only=False, re_snap=False)

    return data_cmd
