from __future__ import annotations

from pathlib import Path

import click

from commands.snapshot_service import (
    SOURCE_CONFIG,
    SOURCE_WORKDIR,
    SOURCE_DATA,
    _get_config_source,
    _get_workdir_source,
    _get_data_source,
    do_snapshot,
    do_restore,
    do_rollback,
    show_status,
    list_snapshots,
)


def _get_source(source_type: str) -> Path | None:
    """Get the source directory for a given type."""
    if source_type == SOURCE_CONFIG:
        return _get_config_source()
    elif source_type == SOURCE_WORKDIR:
        return _get_workdir_source()
    elif source_type == SOURCE_DATA:
        return _get_data_source()
    return None


def _get_sentinel_prefix(source_type: str) -> str:
    """Get the sentinel prefix for a given source type."""
    if source_type == SOURCE_CONFIG:
        return "fast-market"
    elif source_type == SOURCE_WORKDIR:
        return "workdir"
    elif source_type == SOURCE_DATA:
        return "data"
    return "snapshot"


def _is_flat_only(source_type: str) -> bool:
    """Check if the source type should use flat-only mode."""
    return source_type == SOURCE_WORKDIR


SOURCE_TYPE_OPTION = click.option(
    "--source-type",
    "-s",
    type=click.Choice([SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]),
    required=False,
    help="Which directory to backup: workdir, config, or data (default: all)",
)


def _snapshot_all(targets: list[str]):
    """Snapshot all source types (workdir, config, data)."""
    all_sources = [SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]
    target_list = list(targets) if targets else ["."]

    for source_type in all_sources:
        source = _get_source(source_type)
        if source is None:
            click.echo(f"Warning: {source_type} not configured, skipping.", err=True)
            continue
        if not source.exists():
            click.echo(
                f"Warning: {source_type} directory does not exist: {source}, skipping.",
                err=True,
            )
            continue

        flat_only = _is_flat_only(source_type)
        sentinel_prefix = _get_sentinel_prefix(source_type)
        try:
            do_snapshot(
                source_type,
                source,
                target_list,
                flat_only=flat_only,
                sentinel_prefix=sentinel_prefix,
            )
        except Exception as e:
            click.echo(f"Error snapshotting {source_type}: {e}", err=True)


def register():
    @click.group("backup", invoke_without_command=True)
    @click.pass_context
    def backup_cmd(ctx):
        """Manage backups of config, data, and workdir directories.

        Use --source-type workdir|config|data to select which directory to backup.
        Run with no arguments to see available subcommands.
        """
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())

    @backup_cmd.command("snapshot")
    @SOURCE_TYPE_OPTION
    @click.option(
        "--target",
        "-t",
        "targets",
        multiple=True,
        help="Specific files/dirs to snapshot (default: entire directory)",
    )
    @click.pass_context
    def backup_snapshot(ctx, source_type, targets):
        """Create a backup snapshot of the selected directory.

        If --source-type is not specified, snapshots all directories (workdir, config, data).
        """
        if source_type is None:
            # Snapshot all source types
            _snapshot_all(targets)
        else:
            # Snapshot specific source type
            source = _get_source(source_type)
            if source is None:
                click.echo(f"Error: {source_type} not configured.", err=True)
                return
            if not source.exists():
                click.echo(
                    f"Error: {source_type} directory does not exist: {source}", err=True
                )
                return

            target_list = list(targets) if targets else ["."]
            flat_only = _is_flat_only(source_type)
            sentinel_prefix = _get_sentinel_prefix(source_type)
            do_snapshot(
                source_type,
                source,
                target_list,
                flat_only=flat_only,
                sentinel_prefix=sentinel_prefix,
            )

    @backup_cmd.command("restore")
    @SOURCE_TYPE_OPTION
    @click.pass_context
    def backup_restore(ctx, source_type):
        """Restore from the current backup snapshot."""
        source = _get_source(source_type)
        if source is None:
            click.echo(f"Error: {source_type} not configured.", err=True)
            return
        source.mkdir(parents=True, exist_ok=True)
        flat_only = _is_flat_only(source_type)
        do_restore(source_type, source, flat_only=flat_only)

    @backup_cmd.command("status")
    @SOURCE_TYPE_OPTION
    @click.pass_context
    def backup_status(ctx, source_type):
        """Show backup status of the selected directory."""
        source = _get_source(source_type)
        if source is None:
            click.echo(f"{source_type} not configured.")
            return
        flat_only = _is_flat_only(source_type)
        source_exists_check = source_type != SOURCE_WORKDIR or source is not None
        show_status(
            source_type,
            source,
            flat_only=flat_only,
            source_exists_check=source_exists_check,
        )

    @backup_cmd.command("list")
    @SOURCE_TYPE_OPTION
    @click.pass_context
    def backup_list(ctx, source_type):
        """List all backup snapshots of the selected directory."""
        sentinel_prefix = _get_sentinel_prefix(source_type)
        list_snapshots(source_type, sentinel_prefix=sentinel_prefix)

    @backup_cmd.command("rollback")
    @SOURCE_TYPE_OPTION
    @click.argument("snapshot_name", required=False)
    @click.pass_context
    def backup_rollback(ctx, source_type, snapshot_name):
        """Rollback to a specific backup snapshot or the current one."""
        source = _get_source(source_type)
        if source is None:
            click.echo(f"Error: {source_type} not configured.", err=True)
            return
        source.mkdir(parents=True, exist_ok=True)
        flat_only = _is_flat_only(source_type)
        re_snap = source_type == SOURCE_WORKDIR
        do_rollback(
            source_type, source, snapshot_name, flat_only=flat_only, re_snap=re_snap
        )

    return backup_cmd
