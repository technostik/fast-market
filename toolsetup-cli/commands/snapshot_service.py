"""Shared snapshot service for config, workdir, and data directories.

Provides a unified snapshot system with:
- Configurable root snapshot directory
- Support for multiple source directories (config, workdir, data)
- Automatic filtering of .bak* files during snapshots
- Common state management and utilities
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import click

from common.core.config import load_common_config

# Default snapshot root directory
DEFAULT_SNAPSHOT_ROOT = Path.home() / ".local" / "share" / "fast-market" / "snapshots"

# Source directory definitions
SOURCE_CONFIG = "config"
SOURCE_WORKDIR = "workdir"
SOURCE_DATA = "data"


def get_snapshot_root() -> Path:
    """Get the configured snapshot root directory from common config."""
    try:
        config = load_common_config()
        snapshot_root_str = config.get("snapshot_root")
        if snapshot_root_str:
            return Path(snapshot_root_str).expanduser()
    except Exception:
        pass
    return DEFAULT_SNAPSHOT_ROOT


def _get_config_source() -> Path:
    """Get the config source directory."""
    return Path.home() / ".config" / "fast-market"


def _get_data_source() -> Path:
    """Get the XDG data source directory."""
    return Path.home() / ".local" / "share" / "fast-market"


def _get_workdir_source() -> Path | None:
    """Get the workdir root directory from config."""
    try:
        config = load_common_config()
        workdir_root = config.get("workdir_root")
        if workdir_root:
            return Path(workdir_root)
    except Exception:
        pass
    return None


def _get_snapshot_dir_for_source(snapshot_root: Path, source_type: str) -> Path:
    """Get the snapshot subdirectory for a given source type."""
    if source_type == SOURCE_CONFIG:
        return snapshot_root / "config"
    elif source_type == SOURCE_WORKDIR:
        return snapshot_root / "workdir"
    elif source_type == SOURCE_DATA:
        return snapshot_root / "data"
    else:
        raise ValueError(f"Unknown source type: {source_type}")


def _state_path(snapshot_root: Path, source_type: str) -> Path:
    """Get the state file path for a source type."""
    snapshot_dir = _get_snapshot_dir_for_source(snapshot_root, source_type)
    return snapshot_dir / "state.json"


def _load_state(snapshot_root: Path, source_type: str) -> dict:
    """Load state for a source type."""
    state_file = _state_path(snapshot_root, source_type)
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"snapped": False, "targets": [], "sentinel": None}


def _save_state(snapshot_root: Path, source_type: str, state: dict):
    """Save state for a source type."""
    snapshot_dir = _get_snapshot_dir_for_source(snapshot_root, source_type)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    state_file = snapshot_dir / "state.json"
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_snapped(snapshot_root: Path, source_type: str) -> bool:
    """Check if a source type is currently snapped."""
    state = _load_state(snapshot_root, source_type)
    return state.get("snapped", False)


def _should_skip_file(path: Path) -> bool:
    """Check if a file should be skipped during snapshot (e.g., .bak* files)."""
    name = path.name
    # Skip .bak, .bak.1, .bak.2, etc.
    if name == ".bak" or name.startswith(".bak."):
        return True
    # Check if any part of the name has .bak extension pattern
    # e.g., file.yaml.bak, file.yaml.bak.1
    parts = name.split(".")
    for i, part in enumerate(parts):
        if part == "bak":
            return True
    return False


def _copy_tree_no_bak(src: Path, dst: Path) -> int:
    """Recursively copy directory tree, skipping .bak* files.

    Returns number of items copied.
    """
    dst.mkdir(parents=True, exist_ok=True)
    count = 0

    for item in src.iterdir():
        if _should_skip_file(item):
            continue

        item_dst = dst / item.name
        if item.is_dir() and not item.is_symlink():
            count += _copy_tree_no_bak(item, item_dst)
        elif item.is_file() or item.is_symlink():
            if item.is_symlink():
                # Follow symlink and copy target
                real_src = item.resolve()
                if real_src.is_dir():
                    count += _copy_tree_no_bak(real_src, item_dst)
                else:
                    shutil.copy2(str(item), str(item_dst))
                    count += 1
            else:
                shutil.copy2(str(item), str(item_dst))
                count += 1

    return count


def _copy_source_to_snapshot(
    source: Path,
    snapshot_dir: Path,
    targets: list[str] | None = None,
    flat_only: bool = False,
) -> int:
    """Copy source directory/files to snapshot directory.

    Args:
        source: Source directory to snapshot
        snapshot_dir: Destination snapshot directory
        targets: Specific files/dirs to snapshot (None or "." for all)
        flat_only: If True, only copy flat files (no subdirectories)

    Returns:
        Number of files snapped
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snap_count = 0
    snap_all = targets is None or "." in targets

    if snap_all:
        # Snapshot entire directory
        if flat_only:
            # Only copy flat files
            for item in source.iterdir():
                if item.is_file() and not item.is_symlink():
                    if _should_skip_file(item):
                        continue
                    dst = snapshot_dir / item.name
                    shutil.copy2(str(item), str(dst))
                    click.echo(f"Snapped: {item.name}")
                    snap_count += 1
        else:
            # Copy all contents recursively, skipping .bak* files
            for item in source.iterdir():
                if item.name in (".", ".."):
                    continue

                # Skip .bak* files/dirs
                if _should_skip_file(item):
                    click.echo(f"Skipping backup: {item.name}")
                    continue

                dst = snapshot_dir / item.name

                if item.is_dir() and not item.is_symlink():
                    count = _copy_tree_no_bak(item, dst)
                    click.echo(f"Snapped: {item.name}/")
                    snap_count += count + 1
                elif item.is_file() or item.is_symlink():
                    shutil.copy2(str(item), str(dst))
                    click.echo(f"Snapped: {item.name}")
                    snap_count += 1
    else:
        # Snapshot specific targets
        for target in targets:
            src = source / target
            dst = snapshot_dir / target

            if not src.exists():
                click.echo(f"Warning: {src} does not exist, skipping.")
                continue

            # Skip .bak* files
            if src.is_file() and _should_skip_file(src):
                click.echo(f"Skipping backup: {target}")
                continue

            # Ensure parent directory exists in target
            dst.parent.mkdir(parents=True, exist_ok=True)

            # Copy file/directory
            if src.is_dir() and not src.is_symlink():
                if flat_only:
                    # Only copy flat files from the directory
                    for file_item in src.iterdir():
                        if file_item.is_file() and not file_item.is_symlink():
                            if _should_skip_file(file_item):
                                continue
                            file_dst = dst / file_item.name
                            shutil.copy2(str(file_item), str(file_dst))
                            click.echo(f"Snapped: {target}/{file_item.name}")
                            snap_count += 1
                else:
                    count = _copy_tree_no_bak(src, dst)
                    click.echo(f"Snapped: {target}/")
                    snap_count += count + 1
            else:
                if src.is_symlink():
                    # Follow the symlink and copy the target
                    real_src = src.resolve()
                    if real_src.is_dir():
                        count = _copy_tree_no_bak(real_src, dst)
                        snap_count += count + 1
                    else:
                        shutil.copy2(str(real_src), str(dst))
                        snap_count += 1
                else:
                    shutil.copy2(str(src), str(dst))
                    snap_count += 1
                click.echo(f"Snapped: {target}")

    return snap_count


def _restore_from_snapshot(
    source: Path,
    snapshot_dir: Path,
    targets: list[str] | None = None,
    flat_only: bool = False,
):
    """Restore files from snapshot back to source directory.

    Args:
        source: Destination directory to restore to
        snapshot_dir: Source snapshot directory
        targets: Specific files/dirs to restore (None or "." for all)
        flat_only: If True, only restore flat files
    """
    snap_all = targets is None or "." in targets
    restore_count = 0

    if snap_all:
        # Restore entire directory contents
        for item in list(snapshot_dir.iterdir()):
            dst = source / item.name

            # If there's already something there, back it up
            if dst.exists():
                if flat_only and dst.is_dir():
                    # Skip directories in flat-only mode
                    click.echo(f"Skipping directory: {item.name}")
                    continue

                backup_name = f"{dst.name}.pre-restore-{uuid.uuid4().hex[:6]}"
                backup = dst.parent / backup_name
                if dst.is_dir():
                    shutil.move(str(dst), str(backup))
                else:
                    shutil.copy2(str(dst), str(backup))
                    dst.unlink()
                click.echo(f"Backed up: {backup_name}")

            # Copy file back
            if item.is_dir() and not item.is_symlink():
                if dst.exists():
                    shutil.rmtree(str(dst))
                shutil.copytree(str(item), str(dst))
            else:
                shutil.copy2(str(item), str(dst))

            click.echo(f"Restored: {item.name}")
            restore_count += 1
    else:
        # Restore specific targets
        for target in targets:
            src = source / target
            dst = snapshot_dir / target

            if not dst.exists():
                click.echo(f"Warning: snapped file not found: {dst}")
                continue

            # If there's already something there, back it up
            if src.exists():
                if flat_only and src.is_dir():
                    # Skip directories in flat-only mode
                    click.echo(f"Skipping directory: {target}")
                    continue

                backup = src.with_name(f"{src.name}.pre-restore-{uuid.uuid4().hex[:6]}")
                if src.is_dir():
                    shutil.move(str(src), str(backup))
                else:
                    shutil.copy2(str(src), str(backup))
                    src.unlink()
                click.echo(f"Backed up: {backup.name}")

            # Copy file back
            src.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_dir() and not dst.is_symlink():
                if src.exists():
                    shutil.rmtree(str(src))
                shutil.copytree(str(dst), str(src))
            else:
                shutil.copy2(str(dst), str(src))

            click.echo(f"Restored: {target}")
            restore_count += 1

    return restore_count


def do_snapshot(
    source_type: str,
    source: Path,
    targets: list[str] | None = None,
    flat_only: bool = False,
    sentinel_prefix: str = "snapshot",
):
    """Create a snapshot of a source directory.

    Args:
        source_type: One of SOURCE_CONFIG, SOURCE_WORKDIR, SOURCE_DATA
        source: Source directory to snapshot
        targets: Specific files/dirs to snapshot (None or "." for all)
        flat_only: If True, only snapshot flat files
        sentinel_prefix: Prefix for the sentinel directory name
    """
    snapshot_root = get_snapshot_root()
    snapshot_dir = _get_snapshot_dir_for_source(snapshot_root, source_type)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Create sentinel directory
    sentinel = f"{sentinel_prefix}-{uuid.uuid4().hex[:8]}"
    target_dir = snapshot_dir / sentinel
    target_dir.mkdir(parents=True, exist_ok=True)

    state = _load_state(snapshot_root, source_type)
    state["snapped"] = True
    state["targets"] = targets or ["."]
    state["sentinel"] = sentinel
    state["snapshot_date"] = datetime.now().isoformat()
    state["source"] = str(source)

    snap_count = _copy_source_to_snapshot(source, target_dir, targets, flat_only)

    _save_state(snapshot_root, source_type, state)
    click.echo(
        f"{source_type.capitalize()} snapped. {snap_count} item(s) copied to: {target_dir}"
    )


def do_restore(
    source_type: str,
    source: Path,
    flat_only: bool = False,
):
    """Restore from current snapshot.

    Args:
        source_type: One of SOURCE_CONFIG, SOURCE_WORKDIR, SOURCE_DATA
        source: Directory to restore to
        flat_only: If True, only restore flat files
    """
    snapshot_root = get_snapshot_root()

    if not _is_snapped(snapshot_root, source_type):
        click.echo(f"{source_type.capitalize()} is not snapped.")
        return 0

    state = _load_state(snapshot_root, source_type)
    sentinel = state.get("sentinel")
    targets = state.get("targets", [])
    snapshot_dir = _get_snapshot_dir_for_source(snapshot_root, source_type)
    target_dir = snapshot_dir / sentinel

    if not target_dir.exists():
        click.echo(f"Error: Snapshot directory not found: {target_dir}")
        click.echo("Cleaning up state file.")
        _save_state(
            snapshot_root,
            source_type,
            {"snapped": False, "targets": [], "sentinel": None},
        )
        return 0

    # Restore source directory if it doesn't exist
    source.mkdir(parents=True, exist_ok=True)

    restore_count = _restore_from_snapshot(source, target_dir, targets, flat_only)

    # Reset state
    _save_state(
        snapshot_root, source_type, {"snapped": False, "targets": [], "sentinel": None}
    )
    click.echo(
        f"{source_type.capitalize()} restored. {restore_count} item(s) restored."
    )
    return restore_count


def show_status(
    source_type: str,
    source: Path,
    flat_only: bool = False,
    source_exists_check: bool = True,
):
    """Show current snapshot status.

    Args:
        source_type: One of SOURCE_CONFIG, SOURCE_WORKDIR, SOURCE_DATA
        source: Source directory
        flat_only: If True, count only flat files
        source_exists_check: If True, check if source exists
    """
    snapshot_root = get_snapshot_root()
    snapshot_dir = _get_snapshot_dir_for_source(snapshot_root, source_type)

    if source_exists_check and not source.exists():
        click.echo(f"{source_type.capitalize()} directory does not exist: {source}")
        return

    state = _load_state(snapshot_root, source_type)

    if state.get("snapped"):
        click.echo(f"{source_type.capitalize()} is SNAPPED.")
        click.echo(f"  Source: {source}")
        sentinel = state.get("sentinel")
        snap_dir = snapshot_dir / sentinel
        click.echo(f"  Snapped files in: {snap_dir}")
        click.echo(f"  Targets: {', '.join(state.get('targets', []))}")
        click.echo(f"  Snapshot date: {state.get('snapshot_date', 'unknown')}")
        if snap_dir.exists():
            if flat_only:
                flat_count = len([f for f in snap_dir.iterdir() if f.is_file()])
                click.echo(f"  Snapped files: {flat_count}")
            else:
                item_count = len(list(snap_dir.iterdir()))
                click.echo(f"  Snapped items: {item_count}")
    else:
        click.echo(f"{source_type.capitalize()} is NOT snapped.")
        click.echo(f"  Source: {source}")
        if source.exists():
            if flat_only:
                flat_files = [f for f in source.iterdir() if f.is_file()]
                click.echo(f"  Flat files: {len(flat_files)}")
            else:
                item_count = len(list(source.iterdir()))
                click.echo(f"  Items: {item_count}")


def list_snapshots(
    source_type: str,
    sentinel_prefix: str = "snapshot",
):
    """List all snapshot directories.

    Args:
        source_type: One of SOURCE_CONFIG, SOURCE_WORKDIR, SOURCE_DATA
        sentinel_prefix: Prefix to filter snapshot directories
    """
    snapshot_root = get_snapshot_root()
    snapshot_dir = _get_snapshot_dir_for_source(snapshot_root, source_type)

    if not snapshot_dir.exists():
        click.echo("No snapshots found.")
        return

    snapshots = sorted(
        [
            d
            for d in snapshot_dir.iterdir()
            if d.is_dir() and d.name.startswith(sentinel_prefix)
        ],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )

    if not snapshots:
        click.echo("No snapshots found.")
        return

    state = _load_state(snapshot_root, source_type)
    current_sentinel = state.get("sentinel")

    click.echo(f"{source_type.capitalize()} snapshots:")
    for snap in snapshots:
        marker = " (current)" if snap.name == current_sentinel else ""
        mtime = datetime.fromtimestamp(snap.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        item_count = len(list(snap.iterdir()))
        click.echo(f"  {snap.name} - {mtime} - {item_count} item(s){marker} ({snap})")


def do_rollback(
    source_type: str,
    source: Path,
    snapshot_name: str | None = None,
    flat_only: bool = False,
    re_snap: bool = False,
):
    """Rollback to a snapshot.

    Args:
        source_type: One of SOURCE_CONFIG, SOURCE_WORKDIR, SOURCE_DATA
        source: Source directory
        snapshot_name: Specific snapshot to rollback to (None for current)
        flat_only: If True, only handle flat files
        re_snap: If True, re-snap after restore (for workdir behavior)
    """
    snapshot_root = get_snapshot_root()
    snapshot_dir = _get_snapshot_dir_for_source(snapshot_root, source_type)

    if not snapshot_dir.exists():
        click.echo("No snapshots found.")
        return

    state = _load_state(snapshot_root, source_type)

    if not state.get("snapped"):
        click.echo(
            f"{source_type.capitalize()} is not currently snapped. Nothing to rollback."
        )
        return

    sentinel = state.get("sentinel")

    # First restore to bring current state back
    do_restore(source_type, source, flat_only)

    # Then re-snap if requested (workdir behavior)
    if re_snap:
        # We need to get the source again after restore
        if source_type == SOURCE_WORKDIR:
            source_path = _get_workdir_source()
        elif source_type == SOURCE_CONFIG:
            source_path = _get_config_source()
        elif source_type == SOURCE_DATA:
            source_path = _get_data_source()
        else:
            source_path = source

        if source_path and source_path.exists():
            do_snapshot(
                source_type,
                source_path,
                flat_only=flat_only,
                sentinel_prefix=source_type,
            )

    click.echo(f"Rolled back to snapshot: {sentinel}")
