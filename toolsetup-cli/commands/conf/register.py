from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import click

XDG_CONFIG_DIR = Path.home() / ".config" / "fast-market"
CONFGUARD_DATA_DIR = Path.home() / ".local" / "share" / "fast-market" / "confguard"
STATE_FILE = "state.json"


def _ensure_dirs():
    """Ensure required directories exist."""
    CONFGUARD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    XDG_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _state_path() -> Path:
    return CONFGUARD_DATA_DIR / STATE_FILE


def _load_state() -> dict:
    state_file = _state_path()
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"guarded": False, "targets": [], "sentinel": None}


def _save_state(state: dict):
    state_file = _state_path()
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_guarded() -> bool:
    state = _load_state()
    return state.get("guarded", False)


def _do_guard(targets: list[str]):
    """Guard specified files/dirs by moving them and creating symlinks."""
    _ensure_dirs()

    if _is_guarded():
        click.echo("Config is already guarded. Run 'toolsetup conf unguard' first.")
        return

    # Create sentinel directory
    sentinel = f"fast-market-{uuid.uuid4().hex[:8]}"
    target_dir = CONFGUARD_DATA_DIR / sentinel
    target_dir.mkdir(parents=True, exist_ok=True)

    state = _load_state()
    state["guarded"] = True
    state["targets"] = targets
    state["sentinel"] = sentinel
    state["guard_date"] = datetime.now().isoformat()

    guard_all = "." in targets

    if guard_all:
        # Guard entire directory: move all contents, create symlinks
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
            click.echo(f"Guarded: {item.name}")
    else:
        # Guard specific targets
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
            click.echo(f"Guarded: {target}")

    _save_state(state)
    click.echo(f"Config guarded. Files moved to: {target_dir}")


def _do_unguard():
    """Unguard by restoring files and removing symlinks."""
    if not _is_guarded():
        click.echo("Config is not guarded.")
        return

    state = _load_state()
    sentinel = state.get("sentinel")
    targets = state.get("targets", [])
    target_dir = CONFGUARD_DATA_DIR / sentinel

    if not target_dir.exists():
        click.echo(f"Error: Guard directory not found: {target_dir}")
        click.echo("Cleaning up state file.")
        _save_state({"guarded": False, "targets": [], "sentinel": None})
        return

    guard_all = "." in targets

    if guard_all:
        # Restore entire directory contents
        for item in list(target_dir.iterdir()):
            src = XDG_CONFIG_DIR / item.name
            dst = item

            # Remove symlink if it exists
            if src.is_symlink():
                src.unlink()
            elif src.exists():
                # Backup existing content
                backup_name = f"{src.name}.pre-unguard-{uuid.uuid4().hex[:6]}"
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
                click.echo(f"Warning: guarded file not found: {dst}")
                continue

            # Remove symlink
            if src.is_symlink():
                src.unlink()
            elif src.exists():
                # If there's already something there, back it up
                backup = src.with_suffix(f".pre-unguard-{uuid.uuid4().hex[:6]}{src.suffix}")
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
        click.echo(f"Note: guard directory not empty, keeping: {target_dir}")

    # Reset state
    _save_state({"guarded": False, "targets": [], "sentinel": None})
    click.echo("Config unguarded. Files restored.")


def _show_status():
    """Show current guard status."""
    _ensure_dirs()

    if not XDG_CONFIG_DIR.exists():
        click.echo(f"Config directory does not exist: {XDG_CONFIG_DIR}")
        return

    state = _load_state()

    if state.get("guarded"):
        click.echo(f"Config directory is GUARDED.")
        click.echo(f"  Source: {XDG_CONFIG_DIR}")
        click.echo(f"  Guarded files in: {CONFGUARD_DATA_DIR / state['sentinel']}")
        click.echo(f"  Targets: {', '.join(state.get('targets', []))}")
        click.echo(f"  Guard date: {state.get('guard_date', 'unknown')}")
    else:
        click.echo(f"Config directory is NOT guarded.")
        click.echo(f"  Source: {XDG_CONFIG_DIR}")


def _list_backups():
    """List all backup (sentinel) directories."""
    _ensure_dirs()

    if not CONFGUARD_DATA_DIR.exists():
        click.echo("No backups found.")
        return

    backups = sorted(
        [d for d in CONFGUARD_DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("fast-market-")],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        click.echo("No backups found.")
        return

    state = _load_state()
    current_sentinel = state.get("sentinel")

    click.echo("Backups:")
    for backup in backups:
        marker = " (current)" if backup.name == current_sentinel else ""
        mtime = datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        click.echo(f"  {backup.name} - {mtime}{marker}")


def _do_rollback(backup_name: str | None = None):
    """Rollback to a specific backup or the current one."""
    _ensure_dirs()

    if not CONFGUARD_DATA_DIR.exists():
        click.echo("No backups found.")
        return

    state = _load_state()

    if not state.get("guarded"):
        click.echo("Config is not currently guarded. Nothing to rollback.")
        return

    sentinel = state.get("sentinel")
    backup_dir = CONFGUARD_DATA_DIR / sentinel

    if not backup_dir.exists():
        click.echo(f"Error: backup directory not found: {backup_dir}")
        return

    # First unguard to restore current state
    _do_unguard()

    # Then re-guard with the backup contents
    if backup_name:
        backup_dir = CONFGUARD_DATA_DIR / backup_name
        if not backup_dir.exists():
            click.echo(f"Error: backup not found: {backup_name}")
            return

    click.echo(f"Rolled back to backup: {sentinel}")


def register():
    @click.group("conf", invoke_without_command=True)
    @click.pass_context
    def conf_cmd(ctx):
        """Manage XDG config backup/restore.

        Guards ~/.config/fast-market by moving files to a safe location
        and creating symlinks, allowing safe config changes with rollback.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(conf_status)

    @conf_cmd.command("guard")
    @click.option(
        "--target", "-t",
        "targets",
        multiple=True,
        help="Specific files/dirs to guard (default: entire directory)",
    )
    def conf_guard(targets):
        """Guard ~/.config/fast-market config files."""
        target_list = list(targets) if targets else ["."]
        _do_guard(target_list)

    @conf_cmd.command("unguard")
    def conf_unguard():
        """Unguard ~/.config/fast-market, restoring original files."""
        _do_unguard()

    @conf_cmd.command("status")
    def conf_status():
        """Show guard status of ~/.config/fast-market."""
        _show_status()

    @conf_cmd.command("list")
    def conf_list():
        """List all backups."""
        _list_backups()

    @conf_cmd.command("rollback")
    @click.argument("backup", required=False)
    def conf_rollback(backup):
        """Rollback to a specific backup or the current one."""
        _do_rollback(backup)

    return conf_cmd
