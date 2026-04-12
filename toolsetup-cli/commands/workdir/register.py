from __future__ import annotations

from pathlib import Path

import click

from commands.snapshot_service import (
    SOURCE_WORKDIR,
    _get_workdir_source,
    do_snapshot,
    do_restore,
    do_rollback,
    show_status,
    list_snapshots,
)


def register():
    @click.group("workdir", invoke_without_command=True)
    @click.pass_context
    def workdir_cmd(ctx):
        """Manage workdir file snapshot/restore.

        Snapshots files directly in workdir_root (no subdirectories) by
        copying them to a safe location, allowing safe changes with restore.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(workdir_status)

    @workdir_cmd.command("snapshot")
    def workdir_snapshot():
        """Snapshot files directly in workdir_root (flat, no subdirs)."""
        source = _get_workdir_source()
        if source is None:
            click.echo("Error: workdir not configured in common/config.yaml.")
            return
        if not source.exists():
            click.echo(f"Error: workdir does not exist: {source}")
            return
        if not source.is_dir():
            click.echo(f"Error: workdir is not a directory: {source}")
            return
        do_snapshot(SOURCE_WORKDIR, source, targets=None, flat_only=True, sentinel_prefix="workdir")

    @workdir_cmd.command("restore")
    def workdir_restore():
        """Restore files in workdir_root from snapshot (flat, no subdirs)."""
        source = _get_workdir_source()
        if source is None:
            click.echo("Error: workdir not configured in common/config.yaml.")
            return
        source.mkdir(parents=True, exist_ok=True)
        do_restore(SOURCE_WORKDIR, source, flat_only=True)

    @workdir_cmd.command("status")
    def workdir_status():
        """Show snapshot status of workdir."""
        source = _get_workdir_source()
        if source is None:
            click.echo("Workdir not configured in common/config.yaml.")
            return
        show_status(SOURCE_WORKDIR, source, flat_only=True, source_exists_check=False)

    @workdir_cmd.command("list")
    def workdir_list():
        """List all workdir snapshots."""
        list_snapshots(SOURCE_WORKDIR, sentinel_prefix="workdir")

    @workdir_cmd.command("rollback")
    @click.argument("snapshot_name", required=False)
    def workdir_rollback(snapshot_name):
        """Rollback to a specific snapshot or the current one."""
        source = _get_workdir_source()
        if source is None:
            click.echo("Error: workdir not configured in common/config.yaml.")
            return
        source.mkdir(parents=True, exist_ok=True)
        do_rollback(SOURCE_WORKDIR, source, snapshot_name, flat_only=True, re_snap=True)

    return workdir_cmd
