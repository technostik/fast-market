from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import click


def _get_config_source() -> Path:
    """Get the XDG config source directory."""
    return Path.home() / ".config" / "fast-market"


def _clean_bak_files(root: Path, dry_run: bool = False) -> list[Path]:
    """Recursively find and optionally remove *.bak* files under root."""
    bak_files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            if fnmatch.fnmatch(fname, "*.bak*"):
                bak_files.append(Path(dirpath) / fname)

    for f in bak_files:
        if dry_run:
            click.echo(f"[DRY RUN] Would remove: {f}")
        else:
            f.unlink()
            click.echo(f"Removed: {f}")

    return bak_files


def register():
    @click.group("config", invoke_without_command=True)
    @click.pass_context
    def config_cmd(ctx):
        """Manage XDG config directory.

        Use 'toolsetup backup --config' for snapshot/restore operations.
        """
        if ctx.invoked_subcommand is None:
            ctx.invoke(config_clean_bak)

    @config_cmd.command("clean-bak")
    @click.option("--dry-run", "-n", is_flag=True, help="Show what would be removed without deleting")
    def config_clean_bak(dry_run):
        """Remove all *.bak* files recursively from XDG config directory."""
        source = _get_config_source()
        if not source.exists():
            click.echo(f"Config directory does not exist: {source}")
            return
        bak_files = _clean_bak_files(source, dry_run=dry_run)
        if not dry_run:
            click.echo(f"\nRemoved {len(bak_files)} .bak file(s).")
        else:
            click.echo(f"\nWould remove {len(bak_files)} .bak file(s).")

    return config_cmd
