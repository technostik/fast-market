import click
import shutil
import uuid
from pathlib import Path

from common.core.config import (
    load_common_config,
    save_common_config,
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

    @workdir_cmd.command("new")
    @click.option(
        "--prefix", "-p",
        "custom_prefix",
        default=None,
        help="Override the default workdir_prefix",
    )
    def workdir_new(custom_prefix):
        """Create a new workdir and set it as current."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")

        if not workdir_root:
            click.echo("Error: workdir_root not configured. Run: toolsetup workdir init", err=True)
            return

        prefix = custom_prefix if custom_prefix is not None else config.get("workdir_prefix", "work-")
        root_path = Path(workdir_root).expanduser().resolve()
        root_path.mkdir(parents=True, exist_ok=True)

        # Generate short 6-char random ID
        short_id = uuid.uuid4().hex[:6]
        dir_name = f"{prefix}{short_id}"
        new_workdir = root_path / dir_name
        new_workdir.mkdir(parents=True, exist_ok=True)

        config["workdir"] = str(new_workdir)
        save_common_config(config)
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
                # Get modification time for sorting
                mtime = item.stat().st_mtime
                workdirs.append((item, mtime))

        # Sort by modification time, newest first
        workdirs.sort(key=lambda x: x[1], reverse=True)

        if not workdirs:
            click.echo(f"No workdirs found in {root_path} with prefix '{prefix}'")
            return

        for workdir_path, _mtime in workdirs:
            is_current = current_workdir and str(workdir_path) == Path(current_workdir).expanduser().resolve()
            marker = " <- current" if is_current else ""
            click.echo(f"  {workdir_path}{marker}")

    @workdir_cmd.command("prev")
    def workdir_prev():
        """Set current workdir to the previous one in the list."""
        config = load_common_config()
        workdir_root = config.get("workdir_root")
        current_workdir = config.get("workdir")

        if not workdir_root:
            click.echo("Error: workdir_root not configured.", err=True)
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

        if not workdir_root:
            click.echo("Error: workdir_root not configured.", err=True)
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
