from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import click

XDG_CONFIG_DIR = Path.home() / ".config" / "fast-market"
SNAPSHOT_DATA_DIR = Path.home() / ".local" / "share" / "fast-market" / "snapshots"
STATE_FILE = "state.json"

_OLD_CONFGUARD_DIR = Path.home() / ".local" / "share" / "fast-market" / "confguard"


def _ensure_dirs():
    """Ensure required directories exist. Migrate old confguard data if present."""
    SNAPSHOT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    XDG_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Migrate old confguard data to new snapshots directory
    if _OLD_CONFGUARD_DIR.exists():
        for item in _OLD_CONFGUARD_DIR.iterdir():
            if item.is_dir():
                shutil.move(str(item), str(SNAPSHOT_DATA_DIR / item.name))
        # Migrate state file if it exists
        old_state = _OLD_CONFGUARD_DIR / STATE_FILE
        if old_state.exists():
            old_state.rename(SNAPSHOT_DATA_DIR / STATE_FILE)
        _OLD_CONFGUARD_DIR.rmdir()


def _state_path() -> Path:
    return SNAPSHOT_DATA_DIR / STATE_FILE


def _load_state() -> dict:
    state_file = _state_path()
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"snapped": False, "targets": [], "sentinel": None}


def _save_state(state: dict):
    state_file = _state_path()
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_snapped() -> bool:
    state = _load_state()
    return state.get("snapped", False)


def _do_snapshot(targets: list[str]):
    """Snapshot specified files/dirs by moving them and creating symlinks."""
    _ensure_dirs()

    if _is_snapped():
        click.echo("Config is already snapped. Run 'toolsetup conf restore' first.")
        return

    # Create sentinel directory
    sentinel = f"fast-market-{uuid.uuid4().hex[:8]}"
    target_dir = SNAPSHOT_DATA_DIR / sentinel
    target_dir.mkdir(parents=True, exist_ok=True)

    state = _load_state()
    state["snapped"] = True
    state["targets"] = targets
    state["sentinel"] = sentinel
    state["snapshot_date"] = datetime.now().isoformat()

    snap_all = "." in targets

    if snap_all:
        # Snapshot entire directory: move all contents, create symlinks
        for item in XDG_CONFIG_DIR.iterdir():
            if item.name in (".", ".."):
                continue
            dst = target_dir / item.name

            # Move file/directory
            if item.is_dir() and not item.is_symlink():
                shutil.move(str(item), str(dst))
            elif item.is_file() or item.is_symlink():
                shutil.copy2(str(item), str(dst))
                if item.is_symlink():
                    item.unlink()
                else:
                    item.unlink()

            # Create symlink back to original location
            item.symlink_to(dst)
            click.echo(f"Snapped: {item.name}")
    else:
        # Snapshot specific targets
        for target in targets:
            src = XDG_CONFIG_DIR / target
            dst = target_dir / target

            if not src.exists():
                click.echo(f"Warning: {src} does not exist, skipping.")
                continue

            # Ensure parent directory exists in target
            dst.parent.mkdir(parents=True, exist_ok=True)

            # Move file/directory
            if src.is_dir() and not src.is_symlink():
                shutil.move(str(src), str(dst))
            else:
                if src.is_symlink():
                    # Follow the symlink and copy the target
                    real_src = src.resolve()
                    if real_src.is_dir():
                        shutil.copytree(str(real_src), str(dst))
                        src.unlink()
                    else:
                        shutil.copy2(str(real_src), str(dst))
                        src.unlink()
                else:
                    shutil.copy2(str(src), str(dst))
                    src.unlink()

            # Create symlink
            src.symlink_to(dst)
            click.echo(f"Snapped: {target}")

    _save_state(state)
    click.echo(f"Config snapped. Files moved to: {target_dir}")


def _do_restore():
    """Restore by moving files back and removing symlinks."""
    if not _is_snapped():
        click.echo("Config is not snapped.")
        return

    state = _load_state()
    sentinel = state.get("sentinel")
    targets = state.get("targets", [])
    target_dir = SNAPSHOT_DATA_DIR / sentinel

    if not target_dir.exists():
        click.echo(f"Error: Snapshot directory not found: {target_dir}")
        click.echo("Cleaning up state file.")
        _save_state({"snapped": False, "targets": [], "sentinel": None})
        return

    snap_all = "." in targets

    if snap_all:
        # Restore entire directory contents
        for item in list(target_dir.iterdir()):
            src = XDG_CONFIG_DIR / item.name
            dst = item

            # Remove symlink if it exists
            if src.is_symlink():
                src.unlink()
            elif src.exists():
                # Backup existing content
                backup_name = f"{src.name}.pre-restore-{uuid.uuid4().hex[:6]}"
                backup = src.parent / backup_name
                if src.is_dir():
                    shutil.move(str(src), str(backup))
                else:
                    shutil.copy2(str(src), str(backup))
                    src.unlink()

            # Move file back
            shutil.move(str(dst), str(src))
            click.echo(f"Restored: {item.name}")
    else:
        # Restore specific targets
        for target in targets:
            src = XDG_CONFIG_DIR / target
            dst = target_dir / target

            if not dst.exists():
                click.echo(f"Warning: snapped file not found: {dst}")
                continue

            # Remove symlink
            if src.is_symlink():
                src.unlink()
            elif src.exists():
                # If there's already something there, back it up
                backup = src.with_suffix(f".pre-restore-{uuid.uuid4().hex[:6]}{src.suffix}")
                if src.is_dir():
                    shutil.move(str(src), str(backup))
                else:
                    shutil.copy2(str(src), str(backup))
                    src.unlink()

            # Move file back
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            click.echo(f"Restored: {target}")

    # Clean up sentinel directory if empty
    if not any(target_dir.iterdir()):
        shutil.rmtree(str(target_dir))
    else:
        click.echo(f"Note: snapshot directory not empty, keeping: {target_dir}")

    # Reset state
    _save_state({"snapped": False, "targets": [], "sentinel": None})
    click.echo("Config restored. Files restored.")


def _show_status():
    """Show current snapshot status."""
    _ensure_dirs()

    if not XDG_CONFIG_DIR.exists():
        click.echo(f"Config directory does not exist: {XDG_CONFIG_DIR}")
        return

    state = _load_state()

    if state.get("snapped"):
        click.echo(f"Config directory is SNAPPED.")
        click.echo(f"  Source: {XDG_CONFIG_DIR}")
        click.echo(f"  Snapped files in: {SNAPSHOT_DATA_DIR / state['sentinel']}")
        click.echo(f"  Targets: {', '.join(state.get('targets', []))}")
        click.echo(f"  Snapshot date: {state.get('snapshot_date', 'unknown')}")
    else:
        click.echo(f"Config directory is NOT snapped.")
        click.echo(f"  Source: {XDG_CONFIG_DIR}")


def _list_snapshots():
    """List all snapshot directories."""
    _ensure_dirs()

    if not SNAPSHOT_DATA_DIR.exists():
        click.echo("No snapshots found.")
        return

    snapshots = sorted(
        [d for d in SNAPSHOT_DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("fast-market-")],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )

    if not snapshots:
        click.echo("No snapshots found.")
        return

    state = _load_state()
    current_sentinel = state.get("sentinel")

    click.echo("Snapshots:")
    for snap in snapshots:
        marker = " (current)" if snap.name == current_sentinel else ""
        mtime = datetime.fromtimestamp(snap.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        click.echo(f"  {snap.name} - {mtime}{marker}")


def _do_rollback(backup_name: str | None = None):
    """Rollback to a specific snapshot or the current one."""
    _ensure_dirs()

    if not SNAPSHOT_DATA_DIR.exists():
        click.echo("No snapshots found.")
        return

    state = _load_state()

    if not state.get("snapped"):
        click.echo("Config is not currently snapped. Nothing to rollback.")
        return

    sentinel = state.get("sentinel")
    backup_dir = SNAPSHOT_DATA_DIR / sentinel

    if not backup_dir.exists():
        click.echo(f"Error: snapshot directory not found: {backup_dir}")
        return

    # First restore to bring current state back
    _do_restore()

    # Then re-snap with the backup contents
    if backup_name:
        backup_dir = SNAPSHOT_DATA_DIR / backup_name
        if not backup_dir.exists():
            click.echo(f"Error: snapshot not found: {backup_name}")
            return

    click.echo(f"Rolled back to snapshot: {sentinel}")


def register():
    @click.group("conf", invoke_without_command=True)
    @click.pass_context
    def conf_cmd(ctx):
        """Manage XDG config snapshot/restore.

        Snapshots ~/.config/fast-market by moving files to a safe location
        and creating symlinks, allowing safe config changes with restore.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(conf_status)

    @conf_cmd.command("snapshot")
    @click.option(
        "--target", "-t",
        "targets",
        multiple=True,
        help="Specific files/dirs to snapshot (default: entire directory)",
    )
    def conf_snapshot(targets):
        """Snapshot ~/.config/fast-market config files."""
        target_list = list(targets) if targets else ["."]
        _do_snapshot(target_list)

    @conf_cmd.command("restore")
    def conf_restore():
        """Restore ~/.config/fast-market, moving files back."""
        _do_restore()

    @conf_cmd.command("status")
    def conf_status():
        """Show snapshot status of ~/.config/fast-market."""
        _show_status()

    @conf_cmd.command("list")
    def conf_list():
        """List all snapshots."""
        _list_snapshots()

    @conf_cmd.command("rollback")
    @click.argument("snapshot_name", required=False)
    def conf_rollback(snapshot_name):
        """Rollback to a specific snapshot or the current one."""
        _do_rollback(snapshot_name)

    return conf_cmd
