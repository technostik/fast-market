from __future__ import annotations

from pathlib import Path
from datetime import datetime
import uuid
import shutil
import json

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
    get_snapshot_root,
    _load_state,
    _save_state,
    _copy_source_to_snapshot,
    _restore_from_snapshot,
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
    """Snapshot all source types (workdir, config, data) into a unified backup directory."""
    snapshot_root = get_snapshot_root()

    # Create unified backup directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_id = f"backup-{timestamp}-{uuid.uuid4().hex[:8]}"
    backup_dir = snapshot_root / backup_id
    backup_dir.mkdir(parents=True, exist_ok=True)

    all_sources = [SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]
    target_list = list(targets) if targets else ["."]
    total_count = 0
    any_snapped = False

    # Snapshot each source into subdirectory of unified backup
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
        # Snapshot into subdirectory under unified backup
        source_snapshot_dir = backup_dir / source_type
        source_snapshot_dir.mkdir(parents=True, exist_ok=True)

        try:
            count = _copy_source_to_snapshot(
                source, source_snapshot_dir, target_list, flat_only,
                skip_paths={snapshot_root.resolve()}
            )
            if count > 0:
                any_snapped = True
                total_count += count
                click.echo(f"{source_type.capitalize()} snapped: {count} item(s)")

            # Save unified backup state (only for the first snapped source)
            # We store state under the unified backup dir, not the old config/data/workdir dirs
            if any_snapped and not (backup_dir / "state.json").exists():
                unified_state = {
                    "snapped": True,
                    "targets": target_list,
                    "sentinel": backup_id,
                    "snapshot_date": datetime.now().isoformat(),
                    "sources": {},
                }
                unified_state["sources"][source_type] = str(source)
                # Write state to unified backup directory
                (backup_dir / "state.json").write_text(json.dumps(unified_state, indent=2), encoding="utf-8")

        except Exception as e:
            click.echo(f"Error snapshotting {source_type}: {e}", err=True)

    if any_snapped:
        click.echo(f"Unified backup created: {backup_dir} ({total_count} total items)")
        # Clean up old per-source-type snapshot directories (legacy)
        for old_source in [SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]:
            old_dir = snapshot_root / old_source
            if old_dir.exists():
                # Only remove if it only contains state.json (empty snapshots)
                remaining = [f for f in old_dir.iterdir() if f.name != "state.json"]
                if not remaining:
                    # Check if state.json has no snapped data
                    state_file = old_dir / "state.json"
                    if state_file.exists():
                        try:
                            state = json.loads(state_file.read_text(encoding="utf-8"))
                            if not state.get("snapped", False):
                                shutil.rmtree(old_dir, ignore_errors=True)
                                click.echo(f"Cleaned up legacy {old_source} snapshot directory")
                        except Exception:
                            pass
    else:
        # Clean up empty backup dir
        shutil.rmtree(backup_dir, ignore_errors=True)
        click.echo("No sources to backup.", err=True)


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
    @click.option(
        "--backup-id",
        help="Specific unified backup ID to restore from (default: latest)",
    )
    @click.pass_context
    def backup_restore(ctx, source_type, backup_id):
        """Restore from a backup snapshot."""
        snapshot_root = get_snapshot_root()
        
        if source_type is None:
            # Restore all from unified backup
            if backup_id is None:
                # Find latest unified backup
                backups = sorted(
                    [d for d in snapshot_root.iterdir() if d.is_dir() and d.name.startswith("backup-")],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                )
                if not backups:
                    click.echo("No unified backups found.", err=True)
                    ctx.exit(1)
                backup_dir = backups[0]
            else:
                backup_dir = snapshot_root / backup_id
                if not backup_dir.exists():
                    click.echo(f"Backup not found: {backup_id}", err=True)
                    ctx.exit(1)
            
            # Read unified state if available
            unified_state_file = backup_dir / "state.json"
            sources_to_restore = {}
            if unified_state_file.exists():
                unified_state = json.loads(unified_state_file.read_text(encoding="utf-8"))
                sources_to_restore = unified_state.get("sources", {})
            else:
                # Fallback: restore all subdirs that exist
                for st in [SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]:
                    source_snapshot_dir = backup_dir / st
                    if source_snapshot_dir.exists():
                        source = _get_source(st)
                        if source:
                            sources_to_restore[st] = str(source)

            # Restore each source type
            for st, source_path in sources_to_restore.items():
                source = Path(source_path)
                source_snapshot_dir = backup_dir / st
                if source_snapshot_dir.exists():
                    flat_only = _is_flat_only(st)
                    source.mkdir(parents=True, exist_ok=True)
                    count = _restore_from_snapshot(source, source_snapshot_dir, None, flat_only)
                    click.echo(f"{st.capitalize()} restored: {count} item(s)")
            return
        
        # Legacy: restore specific source type
        source = _get_source(source_type)
        if source is None:
            click.echo(f"Error: {source_type} not configured.", err=True)
            ctx.exit(1)
            return
        source.mkdir(parents=True, exist_ok=True)
        flat_only = _is_flat_only(source_type)
        do_restore(source_type, source, flat_only=flat_only)

    @backup_cmd.command("status")
    @SOURCE_TYPE_OPTION
    @click.pass_context
    def backup_status(ctx, source_type):
        """Show backup status of the selected directory."""
        snapshot_root = get_snapshot_root()
        
        if source_type is None:
            # Show status of latest unified backup
            backups = sorted(
                [d for d in snapshot_root.iterdir() if d.is_dir() and d.name.startswith("backup-")],
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            if not backups:
                click.echo("No unified backups found.")
                return
            
            backup_dir = backups[0]
            click.echo(f"Latest unified backup: {backup_dir.name}")
            mtime = datetime.fromtimestamp(backup_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            click.echo(f"  Date: {mtime}")
            for st in [SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]:
                source = _get_source(st)
                src_dir = backup_dir / st
                if src_dir.exists():
                    item_count = len(list(src_dir.iterdir()))
                    click.echo(f"  {st}: {item_count} item(s)")
                elif source and source.exists():
                    click.echo(f"  {st}: NOT in backup (source exists)")
                else:
                    click.echo(f"  {st}: NOT in backup (not configured)")
            return
        
        source = _get_source(source_type)
        if source is None:
            click.echo(f"{source_type} not configured.", err=True)
            ctx.exit(1)
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
        snapshot_root = get_snapshot_root()
        
        if source_type is None:
            # List unified backups
            if not snapshot_root.exists():
                click.echo("No snapshots found.")
                return
            
            backups = sorted(
                [d for d in snapshot_root.iterdir() if d.is_dir() and d.name.startswith("backup-")],
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            
            if not backups:
                click.echo("No unified backups found.")
                return
            
            click.echo("Unified backups:")
            for backup in backups:
                mtime = datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                # Count items in each source subdirectory
                total_items = 0
                for src_type in [SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]:
                    src_dir = backup / src_type
                    if src_dir.exists():
                        total_items += len(list(src_dir.iterdir()))
                click.echo(f"  {backup.name} - {mtime} - {total_items} item(s) ({backup})")
        else:
            # Legacy: list per-source-type snapshots
            sentinel_prefix = _get_sentinel_prefix(source_type)
            list_snapshots(source_type, sentinel_prefix=sentinel_prefix)

    @backup_cmd.command("rollback")
    @SOURCE_TYPE_OPTION
    @click.argument("snapshot_name", required=False)
    @click.option(
        "--backup-id",
        help="Specific unified backup ID to rollback to (default: latest)",
    )
    @click.pass_context
    def backup_rollback(ctx, source_type, snapshot_name, backup_id):
        """Rollback to a specific backup snapshot or the current one."""
        snapshot_root = get_snapshot_root()
        
        if source_type is None:
            # Rollback all from unified backup
            if backup_id is None:
                # Find latest unified backup
                backups = sorted(
                    [d for d in snapshot_root.iterdir() if d.is_dir() and d.name.startswith("backup-")],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                )
                if not backups:
                    click.echo("No unified backups found.", err=True)
                    ctx.exit(1)
                backup_dir = backups[0]
            else:
                backup_dir = snapshot_root / backup_id
                if not backup_dir.exists():
                    click.echo(f"Backup not found: {backup_id}", err=True)
                    ctx.exit(1)
            
            # Restore each source type
            for st in [SOURCE_WORKDIR, SOURCE_CONFIG, SOURCE_DATA]:
                source = _get_source(st)
                if source is None:
                    continue
                source_snapshot_dir = backup_dir / st
                if source_snapshot_dir.exists():
                    flat_only = _is_flat_only(st)
                    source.mkdir(parents=True, exist_ok=True)
                    count = _restore_from_snapshot(source, source_snapshot_dir, None, flat_only)
                    click.echo(f"{st.capitalize()} rolled back: {count} item(s)")
                    
                    # Re-snap if workdir (for rollback re_snap behavior)
                    if st == SOURCE_WORKDIR:
                        do_snapshot(st, source, ["."], flat_only, sentinel_prefix=st)
            return
        
        # Legacy: rollback specific source type
        source = _get_source(source_type)
        if source is None:
            click.echo(f"Error: {source_type} not configured.", err=True)
            ctx.exit(1)
            return
        source.mkdir(parents=True, exist_ok=True)
        flat_only = _is_flat_only(source_type)
        re_snap = source_type == SOURCE_WORKDIR
        do_rollback(source_type, source, snapshot_name, flat_only=flat_only, re_snap=re_snap)

    return backup_cmd
