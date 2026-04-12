from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import click

from common.core.config import load_common_config

WORKDIR_SNAPSHOT_DATA_DIR = Path.home() / ".local" / "share" / "fast-market" / "workdir-snapshots"
STATE_FILE = "state.json"


def _ensure_dirs():
    """Ensure required directories exist."""
    WORKDIR_SNAPSHOT_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _state_path() -> Path:
    return WORKDIR_SNAPSHOT_DATA_DIR / STATE_FILE


def _load_state() -> dict:
    state_file = _state_path()
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"snapped": False, "sentinel": None}


def _save_state(state: dict):
    state_file = _state_path()
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_snapped() -> bool:
    state = _load_state()
    return state.get("snapped", False)


def _get_workdir_root() -> Path | None:
    """Get the workdir_root from common/config.yaml."""
    try:
        config = load_common_config()
        workdir = config.get("workdir")
        if workdir:
            return Path(workdir)
    except Exception:
        pass
    return None


def _do_snapshot():
    """Snapshot files directly in workdir_root (flat, no subdirs) by copying them to a sentinel directory."""
    _ensure_dirs()

    if _is_snapped():
        click.echo("Workdir is already snapped. Run 'toolsetup workdir restore' first.")
        return

    workdir_root = _get_workdir_root()
    if workdir_root is None:
        click.echo("Error: workdir not configured in common/config.yaml.")
        return

    if not workdir_root.exists():
        click.echo(f"Error: workdir does not exist: {workdir_root}")
        return

    if not workdir_root.is_dir():
        click.echo(f"Error: workdir is not a directory: {workdir_root}")
        return

    # Create sentinel directory
    sentinel = f"workdir-{uuid.uuid4().hex[:8]}"
    target_dir = WORKDIR_SNAPSHOT_DATA_DIR / sentinel
    target_dir.mkdir(parents=True, exist_ok=True)

    state = _load_state()
    state["snapped"] = True
    state["sentinel"] = sentinel
    state["snapshot_date"] = datetime.now().isoformat()
    state["workdir"] = str(workdir_root)

    snap_count = 0

    # Only snapshot files directly in workdir_root (no subdirectories)
    for item in workdir_root.iterdir():
        # Skip directories - only snapshot flat files
        if item.is_dir():
            continue

        dst = target_dir / item.name
        shutil.copy2(str(item), str(dst))
        click.echo(f"Snapped: {item.name}")
        snap_count += 1

    _save_state(state)
    click.echo(f"Workdir snapped. {snap_count} file(s) copied to: {target_dir}")


def _do_restore():
    """Restore by copying files back from snapshot to workdir_root (flat, no subdirs)."""
    if not _is_snapped():
        click.echo("Workdir is not snapped.")
        return

    state = _load_state()
    sentinel = state.get("sentinel")
    target_dir = WORKDIR_SNAPSHOT_DATA_DIR / sentinel

    if not target_dir.exists():
        click.echo(f"Error: Snapshot directory not found: {target_dir}")
        click.echo("Cleaning up state file.")
        _save_state({"snapped": False, "sentinel": None})
        return

    workdir_root = Path(state.get("workdir", ""))
    if not workdir_root or not workdir_root.exists():
        # Try to get from config as fallback
        workdir_root = _get_workdir_root()
        if workdir_root is None:
            click.echo("Error: workdir not configured in common/config.yaml.")
            return

    restore_count = 0

    # Restore only files (flat, no subdirs)
    for item in list(target_dir.iterdir()):
        dst = workdir_root / item.name

        # If there's already something there, back it up
        if dst.exists():
            if dst.is_dir():
                # Skip directories during restore
                click.echo(f"Skipping directory: {item.name}")
                continue
            backup_name = f"{dst.name}.pre-restore-{uuid.uuid4().hex[:6]}"
            backup = dst.parent / backup_name
            shutil.copy2(str(dst), str(backup))
            dst.unlink()
            click.echo(f"Backed up: {backup_name}")

        # Copy file back
        shutil.copy2(str(item), str(dst))
        click.echo(f"Restored: {item.name}")
        restore_count += 1

    # Reset state
    _save_state({"snapped": False, "sentinel": None})
    click.echo(f"Workdir restored. {restore_count} file(s) restored to: {workdir_root}")


def _show_status():
    """Show current snapshot status."""
    _ensure_dirs()

    workdir_root = _get_workdir_root()
    if workdir_root is None:
        click.echo("Workdir not configured in common/config.yaml.")
        return

    if not workdir_root.exists():
        click.echo(f"Workdir does not exist: {workdir_root}")
        return

    state = _load_state()

    if state.get("snapped"):
        click.echo("Workdir is SNAPPED.")
        click.echo(f"  Source: {workdir_root}")
        click.echo(f"  Snapped files in: {WORKDIR_SNAPSHOT_DATA_DIR / state['sentinel']}")
        click.echo(f"  Snapshot date: {state.get('snapshot_date', 'unknown')}")
        snap_count = len(list((WORKDIR_SNAPSHOT_DATA_DIR / state['sentinel']).iterdir())) if (WORKDIR_SNAPSHOT_DATA_DIR / state['sentinel']).exists() else 0
        click.echo(f"  Snapped files: {snap_count}")
    else:
        click.echo("Workdir is NOT snapped.")
        click.echo(f"  Source: {workdir_root}")
        # Count flat files
        flat_files = [f for f in workdir_root.iterdir() if f.is_file()]
        click.echo(f"  Flat files: {len(flat_files)}")


def _list_snapshots():
    """List all snapshot directories."""
    _ensure_dirs()

    if not WORKDIR_SNAPSHOT_DATA_DIR.exists():
        click.echo("No snapshots found.")
        return

    snapshots = sorted(
        [d for d in WORKDIR_SNAPSHOT_DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("workdir-")],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )

    if not snapshots:
        click.echo("No snapshots found.")
        return

    state = _load_state()
    current_sentinel = state.get("sentinel")

    click.echo("Workdir snapshots:")
    for snap in snapshots:
        marker = " (current)" if snap.name == current_sentinel else ""
        mtime = datetime.fromtimestamp(snap.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        file_count = len(list(snap.iterdir()))
        click.echo(f"  {snap.name} - {mtime} - {file_count} file(s){marker}")


def _do_rollback(backup_name: str | None = None):
    """Rollback to a specific snapshot or the current one."""
    _ensure_dirs()

    if not WORKDIR_SNAPSHOT_DATA_DIR.exists():
        click.echo("No snapshots found.")
        return

    state = _load_state()

    if not state.get("snapped"):
        click.echo("Workdir is not currently snapped. Nothing to rollback.")
        return

    sentinel = state.get("sentinel")
    backup_dir = WORKDIR_SNAPSHOT_DATA_DIR / sentinel

    if not backup_dir.exists():
        click.echo(f"Error: snapshot directory not found: {backup_dir}")
        return

    # First restore to bring current state back
    _do_restore()

    # Then re-snap
    _do_snapshot()

    click.echo(f"Rolled back to snapshot: {sentinel}")


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
        _do_snapshot()

    @workdir_cmd.command("restore")
    def workdir_restore():
        """Restore files in workdir_root from snapshot (flat, no subdirs)."""
        _do_restore()

    @workdir_cmd.command("status")
    def workdir_status():
        """Show snapshot status of workdir."""
        _show_status()

    @workdir_cmd.command("list")
    def workdir_list():
        """List all workdir snapshots."""
        _list_snapshots()

    @workdir_cmd.command("rollback")
    @click.argument("snapshot_name", required=False)
    def workdir_rollback(snapshot_name):
        """Rollback to a specific snapshot or the current one."""
        _do_rollback(snapshot_name)

    return workdir_cmd
