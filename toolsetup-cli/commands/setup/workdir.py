import click
import shutil
import time
import uuid
from pathlib import Path

from common.core.config import (
    load_common_config,
    save_common_config,
    is_workdir_locked,
    add_workdir_lock,
    remove_workdir_lock,
    get_lock_wait_timeout,
)


def register():
    @click.group("workdir", invoke_without_command=True)
    @click.pass_context
    def workdir_cmd(ctx):
        """Manage workdir subdirectories within workdir_root.

        Allows creating, listing, and switching between isolated work directories.
        Run with no arguments to list existing workdirs.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(workdir_list_cmd)

    @workdir_cmd.command("init")
    @click.argument("workdir_root_path", type=click.Path(), required=True)
    @click.option(
        "--prefix", "-p",
        "workdir_prefix",
        default="work-",
        help="Default prefix for new workdirs (default: work-)",
    )
    def workdir_init(workdir_root_path, workdir_prefix):
        """Initialize workdir configuration."""
        config = load_common_config()
        root_path = Path(workdir_root_path).expanduser().resolve()
        root_path.mkdir(parents=True, exist_ok=True)

        config["workdir_root"] = str(root_path)
        config["workdir_prefix"] = workdir_prefix
        save_common_config(config)
        click.echo(f"Workdir root initialized: {root_path}")
        click.echo(f"Workdir prefix set to: {workdir_prefix}")

    @workdir_cmd.command("show")
    def workdir_show():
        """Display current workdir."""
        config = load_common_config()
        current_workdir = config.get("workdir")

        if not current_workdir:
            click.echo("No workdir configured. Run: toolsetup workdir init <path>")
            return

        workdir_path = Path(current_workdir).expanduser().resolve()
        click.echo(f"{workdir_path}")

    @workdir_cmd.command("reset")
    def workdir_reset():
        """Reset current workdir to workdir_root."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")

        if not workdir_root:
            click.echo("Error: workdir_root not configured. Run: toolsetup workdir init", err=True)
            return

        root_path = Path(workdir_root).expanduser().resolve()
        if not root_path.exists():
            click.echo(f"Error: workdir_root does not exist: {root_path}", err=True)
            return

        config["workdir"] = str(root_path)
        save_common_config(config)
        click.echo(f"Workdir reset to: {root_path}")

    @workdir_cmd.command("lock")
    def workdir_lock():
        """Add a .lock file to the current workdir to prevent changes."""
        config = load_common_config()
        current_workdir = config.get("workdir")

        if not current_workdir:
            click.echo("No workdir configured. Run: toolsetup workdir init <path>", err=True)
            return

        workdir_path = Path(current_workdir).expanduser().resolve()
        if not workdir_path.exists():
            click.echo(f"Error: workdir does not exist: {workdir_path}", err=True)
            return

        if is_workdir_locked(str(workdir_path)):
            click.echo(f"Workdir is already locked: {workdir_path}")
            return

        add_workdir_lock(str(workdir_path))
        click.echo(f"Workdir locked: {workdir_path}")

    @workdir_cmd.command("unlock")
    def workdir_unlock():
        """Remove the .lock file from the current workdir to allow changes."""
        config = load_common_config()
        current_workdir = config.get("workdir")

        if not current_workdir:
            click.echo("No workdir configured. Run: toolsetup workdir init <path>", err=True)
            return

        workdir_path = Path(current_workdir).expanduser().resolve()
        if not workdir_path.exists():
            click.echo(f"Error: workdir does not exist: {workdir_path}", err=True)
            return

        if not is_workdir_locked(str(workdir_path)):
            click.echo(f"Workdir is not locked: {workdir_path}")
            return

        remove_workdir_lock(str(workdir_path))
        click.echo(f"Workdir unlocked: {workdir_path}")

    @workdir_cmd.command("islocked")
    def workdir_islocked():
        """Check if the current workdir is locked."""
        config = load_common_config()
        current_workdir = config.get("workdir")

        if not current_workdir:
            click.echo("No workdir configured. Run: toolsetup workdir init <path>", err=True)
            return

        workdir_path = Path(current_workdir).expanduser().resolve()
        if not workdir_path.exists():
            click.echo(f"Error: workdir does not exist: {workdir_path}", err=True)
            return

        if is_workdir_locked(str(workdir_path)):
            click.echo(f"Workdir is LOCKED: {workdir_path}")
        else:
            click.echo(f"Workdir is NOT locked: {workdir_path}")

    @workdir_cmd.command("release")
    @click.option(
        "--bypass",
        is_flag=True,
        help="Release current lock and create a new workdir",
    )
    def workdir_release(bypass):
        """Release the lock and reset to previous workdir, or create new workdir with --bypass."""
        config = load_common_config()
        current_workdir = config.get("workdir")
        previous_workdir = config.get("previous_workdir")

        if not current_workdir:
            click.echo("No workdir configured.", err=True)
            return

        workdir_path = Path(current_workdir).expanduser().resolve()
        was_locked = is_workdir_locked(str(workdir_path))

        if bypass:
            remove_workdir_lock(str(workdir_path))
            click.echo(f"Released lock: {workdir_path}")

            workdir_root = config.get("workdir_root")
            if not workdir_root:
                click.echo("Error: workdir_root not configured. Run: toolsetup workdir init", err=True)
                return

            prefix = config.get("workdir_prefix", "work-")
            root_path = Path(workdir_root).expanduser().resolve()
            root_path.mkdir(parents=True, exist_ok=True)

            short_id = uuid.uuid4().hex[:6]
            dir_name = f"{prefix}{short_id}"
            new_workdir = root_path / dir_name
            new_workdir.mkdir(parents=True, exist_ok=True)

            config["previous_workdir"] = current_workdir
            config["workdir"] = str(new_workdir)
            save_common_config(config)

            add_workdir_lock(str(new_workdir))
            click.echo(f"Created new workdir: {new_workdir} (locked)")
            return

        if not was_locked:
            click.echo("Workdir is not locked. Use --bypass to create a new workdir.", err=True)
            return

        if previous_workdir:
            prev_path = Path(previous_workdir).expanduser().resolve()
            if prev_path.exists():
                remove_workdir_lock(str(workdir_path))
                config["workdir"] = previous_workdir
                config["previous_workdir"] = current_workdir
                save_common_config(config)
                click.echo(f"Released and switched to previous: {prev_path}")
                return

        remove_workdir_lock(str(workdir_path))
        click.echo(f"Released lock: {workdir_path} (no previous workdir to switch to)")

    @workdir_cmd.command("new")
    @click.option(
        "--prefix", "-p",
        "custom_prefix",
        default=None,
        help="Override the default workdir_prefix",
    )
    @click.option(
        "--force", "-f",
        is_flag=True,
        help="Force create new workdir even if current is locked (skips wait)",
    )
    @click.option(
        "--no-wait",
        is_flag=True,
        help="Don't wait if current workdir is locked, fail immediately",
    )
    def workdir_new(custom_prefix, force, no_wait):
        """Create a new workdir and set it as current. Automatically adds .lock if none exists."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")
        current_workdir = config.get("workdir")

        if not workdir_root:
            click.echo("Error: workdir_root not configured. Run: toolsetup workdir init", err=True)
            return

        if current_workdir and is_workdir_locked(current_workdir) and not force:
            if no_wait:
                click.echo(f"Error: current workdir is locked. Use --force to create anyway or --no-wait to fail immediately.", err=True)
                return

            timeout = get_lock_wait_timeout()
            start_time = time.time()
            click.echo(f"Current workdir is locked. Waiting up to {timeout}s for unlock...", err=True)

            while time.time() - start_time < timeout:
                time.sleep(1)
                if not is_workdir_locked(current_workdir):
                    click.echo("Workdir unlocked.", err=True)
                    break
            else:
                click.echo(f"Error: Timeout waiting for workdir to unlock. Use --force to create anyway.", err=True)
                return

        prefix = custom_prefix if custom_prefix is not None else config.get("workdir_prefix", "work-")
        root_path = Path(workdir_root).expanduser().resolve()
        root_path.mkdir(parents=True, exist_ok=True)

        short_id = uuid.uuid4().hex[:6]
        dir_name = f"{prefix}{short_id}"
        new_workdir = root_path / dir_name
        new_workdir.mkdir(parents=True, exist_ok=True)

        config["previous_workdir"] = config.get("workdir")
        config["workdir"] = str(new_workdir)
        save_common_config(config)

        if not is_workdir_locked(str(new_workdir)):
            add_workdir_lock(str(new_workdir))
            click.echo(f"Created workdir: {new_workdir} (locked)")
        else:
            click.echo(f"Created workdir: {new_workdir}")

    @workdir_cmd.command("list")
    def workdir_list_cmd():
        """List workdirs sorted by time (newest first)."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")
        current_workdir = config.get("workdir")

        if not workdir_root:
            click.echo("Error: workdir_root not configured.", err=True)
            return

        root_path = Path(workdir_root).expanduser().resolve()
        if not root_path.exists():
            click.echo(f"Workdir root is empty: {root_path}")
            return

        prefix = config.get("workdir_prefix", "work-")
        workdirs = []

        for item in root_path.iterdir():
            if item.is_dir() and item.name.startswith(prefix):
                mtime = item.stat().st_mtime
                is_locked = is_workdir_locked(str(item))
                workdirs.append((item, mtime, is_locked))

        workdirs.sort(key=lambda x: x[1], reverse=True)

        if not workdirs:
            click.echo(f"No workdirs found in {root_path} with prefix '{prefix}'")
            return

        locked_count = sum(1 for _, _, locked in workdirs if locked)
        if locked_count > 0:
            click.echo(f"*** {locked_count} LOCKED WORKDIR(S) ***", err=True)

        for workdir_path, _mtime, is_locked in workdirs:
            current_resolved = Path(current_workdir).expanduser().resolve() if current_workdir else None
            is_current = current_resolved and str(workdir_path) == str(current_resolved)
            if is_current:
                if is_locked:
                    click.echo(f">>> {workdir_path} <<< (current) [LOCKED]", err=True)
                else:
                    click.echo(f">>> {workdir_path} <<< (current)", err=True)
            elif is_locked:
                click.echo(f"  {workdir_path} [LOCKED]")
            else:
                click.echo(f"  {workdir_path}")

    @workdir_cmd.command("prev")
    def workdir_prev():
        """Set current workdir to the previous one in the list."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")
        current_workdir = config.get("workdir")

        if not workdir_root:
            click.echo("Error: workdir_root not configured.", err=True)
            return

        if current_workdir and is_workdir_locked(current_workdir):
            click.echo(f"Error: workdir is locked. Run 'toolsetup workdir release' to unlock.", err=True)
            return

        root_path = Path(workdir_root).expanduser().resolve()
        if not root_path.exists():
            click.echo(f"Error: workdir_root does not exist: {root_path}", err=True)
            return

        prefix = config.get("workdir_prefix", "work-")
        workdirs = []

        for item in root_path.iterdir():
            if item.is_dir() and item.name.startswith(prefix):
                mtime = item.stat().st_mtime
                workdirs.append((item, mtime))

        # Sort by modification time, newest first
        workdirs.sort(key=lambda x: x[1], reverse=True)

        if not workdirs:
            click.echo("No workdirs found.", err=True)
            return

        # Find current workdir index
        current_idx = None
        if current_workdir:
            current_resolved = Path(current_workdir).expanduser().resolve()
            for i, (workdir_path, _) in enumerate(workdirs):
                if workdir_path == current_resolved:
                    current_idx = i
                    break

        if current_idx is None:
            # If no current workdir or not found, use the first (newest)
            click.echo("No current workdir found. Using newest.", err=True)
            new_workdir = workdirs[0][0]
        elif current_idx >= len(workdirs) - 1:
            # Already at the last one
            click.echo("Already at the oldest workdir.", err=True)
            return
        else:
            # Move to previous (next in the list, which is older)
            new_workdir = workdirs[current_idx + 1][0]

        config["workdir"] = str(new_workdir)
        save_common_config(config)
        click.echo(f"Workdir changed to: {new_workdir}")

    @workdir_cmd.command("last")
    def workdir_last():
        """Set current workdir to the most recent one."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")
        current_workdir = config.get("workdir")

        if not workdir_root:
            click.echo("Error: workdir_root not configured.", err=True)
            return

        if current_workdir and is_workdir_locked(current_workdir):
            click.echo(f"Error: workdir is locked. Run 'toolsetup workdir release' to unlock.", err=True)
            return

        root_path = Path(workdir_root).expanduser().resolve()
        if not root_path.exists():
            click.echo(f"Error: workdir_root does not exist: {root_path}", err=True)
            return

        prefix = config.get("workdir_prefix", "work-")
        workdirs = []

        for item in root_path.iterdir():
            if item.is_dir() and item.name.startswith(prefix):
                mtime = item.stat().st_mtime
                workdirs.append((item, mtime))

        # Sort by modification time, newest first
        workdirs.sort(key=lambda x: x[1], reverse=True)

        if not workdirs:
            click.echo("No workdirs found.", err=True)
            return

        newest_workdir = workdirs[0][0]
        config["workdir"] = str(newest_workdir)
        save_common_config(config)
        click.echo(f"Workdir changed to: {newest_workdir}")

    @workdir_cmd.command("clean")
    @click.option(
        "--prefix", "-p",
        "custom_prefix",
        default=None,
        help="Override the default workdir_prefix",
    )
    @click.option(
        "--force", "-f",
        is_flag=True,
        help="Skip confirmation prompt",
    )
    def workdir_clean(custom_prefix, force):
        """Delete all workdirs matching the current prefix."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")

        if not workdir_root:
            click.echo("Error: workdir_root not configured.", err=True)
            return

        prefix = custom_prefix if custom_prefix is not None else config.get("workdir_prefix", "work-")
        root_path = Path(workdir_root).expanduser().resolve()

        if not root_path.exists():
            click.echo(f"Workdir root is empty: {root_path}")
            return

        workdirs_to_delete = []
        for item in root_path.iterdir():
            if item.is_dir() and item.name.startswith(prefix):
                workdirs_to_delete.append(item)

        if not workdirs_to_delete:
            click.echo(f"No workdirs found in {root_path} with prefix '{prefix}'")
            return

        if not force:
            click.echo(f"Found {len(workdirs_to_delete)} workdir(s) to delete:")
            for wd in workdirs_to_delete:
                click.echo(f"  {wd}")
            if not click.confirm("Delete these workdirs? (files inside will be removed)"):
                click.echo("Cancelled.")
                return

        deleted_count = 0
        for wd in workdirs_to_delete:
            try:
                shutil.rmtree(wd)
                deleted_count += 1
            except Exception as e:
                click.echo(f"Error removing {wd}: {e}", err=True)

        click.echo(f"Deleted {deleted_count} workdir(s).")

        # Reset workdir to workdir_root
        workdir_root = config.get("workdir_root")
        if workdir_root:
            root_path = Path(workdir_root).expanduser().resolve()
            if root_path.exists():
                config["workdir"] = str(root_path)
                save_common_config(config)
                click.echo(f"Workdir reset to: {root_path}")

    return workdir_cmd
