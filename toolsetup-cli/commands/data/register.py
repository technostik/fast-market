from __future__ import annotations

from pathlib import Path

import click


def _get_data_source() -> Path:
    """Get the XDG data source directory."""
    return Path.home() / ".local" / "share" / "fast-market"


def register():
    @click.group("data", invoke_without_command=True)
    @click.pass_context
    def data_cmd(ctx):
        """Manage XDG data directory.

        Use 'toolsetup backup --data' for snapshot/restore operations.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(data_list)

    @data_cmd.command("list")
    def data_list():
        """List contents of XDG data directory."""
        source = _get_data_source()
        if not source.exists():
            click.echo(f"Data directory does not exist: {source}")
            return

        click.echo(f"Data directory: {source}")
        items = list(source.iterdir())
        if not items:
            click.echo("  (empty)")
            return

        for item in sorted(items):
            marker = "/" if item.is_dir() else ""
            click.echo(f"  {item.name}{marker}")

    return data_cmd
