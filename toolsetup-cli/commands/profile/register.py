from __future__ import annotations

import os
import shutil
from pathlib import Path

import click

from common.core.profile import (
    SHARED,
    DEFAULT_PROFILE,
    read_active_pointer,
    write_active_pointer,
    validate_profile_name,
    resolve_profile,
    ProfileError,
)


def _xdg(env: str, default: Path) -> Path:
    return Path(os.environ.get(env, default))


def _roots() -> dict[str, Path]:
    """The three fast-market XDG roots that hold per-profile data."""
    home = Path.home()
    return {
        "config": _xdg("XDG_CONFIG_HOME", home / ".config") / "fast-market",
        "data": _xdg("XDG_DATA_HOME", home / ".local" / "share") / "fast-market",
        "cache": _xdg("XDG_CACHE_HOME", home / ".cache") / "fast-market",
    }


def _profiles_dir(root: Path) -> Path:
    return root / "profiles"


def _profile_dirs(name: str) -> dict[str, Path]:
    return {kind: _profiles_dir(root) / name for kind, root in _roots().items()}


def _list_profile_names() -> list[str]:
    names: set[str] = set()
    for root in _roots().values():
        pdir = _profiles_dir(root)
        if pdir.exists():
            for child in pdir.iterdir():
                if child.is_dir() and child.name != SHARED:
                    names.add(child.name)
    return sorted(names)


def register():
    @click.group("profile", invoke_without_command=True)
    @click.pass_context
    def profile_cmd(ctx):
        """Manage personas/profiles (multi-identity support)."""
        if ctx.invoked_subcommand is None:
            ctx.invoke(profile_list)

    # ── list ──────────────────────────────────────────────────────────────
    @profile_cmd.command("list")
    def profile_list():
        """List profiles and mark the active one."""
        active = resolve_profile()
        names = _list_profile_names()
        if not names:
            click.echo("No profiles yet. Create one with: toolsetup profile create <name>")
            click.echo(f"(active resolves to '{active}')")
            return
        click.echo("Profiles:")
        for name in names:
            mark = " *" if name == active else ""
            click.echo(f"  {name}{mark}")
        shared = _profile_dirs(SHARED)["config"]
        if shared.exists():
            click.echo(f"\n(shared base '{SHARED}' present — inherited by all)")
        click.echo(f"\nActive: {active}")

    # ── show-shared ───────────────────────────────────────────────────────
    @profile_cmd.command("show-shared")
    def profile_show_shared():
        """Show the contents of the _shared base layer."""
        any_found = False
        for kind, path in _profile_dirs(SHARED).items():
            if path.exists():
                any_found = True
                click.echo(f"{kind}: {path}")
                for item in sorted(path.rglob("*")):
                    if item.is_file():
                        click.echo(f"    {item.relative_to(path)}")
        if not any_found:
            click.echo(f"No '{SHARED}' base layer yet.")

    # ── show-path ─────────────────────────────────────────────────────────
    @profile_cmd.command("show-path")
    @click.argument("name", required=False)
    def profile_show_path(name):
        """Show resolved config/data/cache paths for a profile (default: active)."""
        name = name or resolve_profile()
        try:
            validate_profile_name(name)
        except ProfileError as exc:
            raise click.ClickException(str(exc))
        for kind, path in _profile_dirs(name).items():
            exists = "" if path.exists() else "  (not created)"
            click.echo(f"{kind}: {path}{exists}")

    # ── create ────────────────────────────────────────────────────────────
    @profile_cmd.command("create")
    @click.argument("name")
    def profile_create(name):
        """Create a new, empty profile."""
        try:
            validate_profile_name(name)
        except ProfileError as exc:
            raise click.ClickException(str(exc))
        if name == SHARED:
            raise click.ClickException(f"'{SHARED}' is reserved.")
        dirs = _profile_dirs(name)
        if dirs["config"].exists():
            raise click.ClickException(f"Profile '{name}' already exists.")
        dirs["config"].mkdir(parents=True, exist_ok=True)
        click.echo(f"Created profile '{name}'. Switch to it with: toolsetup profile use {name}")

    # ── clone ─────────────────────────────────────────────────────────────
    @profile_cmd.command("clone")
    @click.argument("src")
    @click.argument("dst")
    def profile_clone(src, dst):
        """Clone SRC profile into a new DST profile (config + data + cache)."""
        for n in (src, dst):
            try:
                validate_profile_name(n)
            except ProfileError as exc:
                raise click.ClickException(str(exc))
        if dst == SHARED:
            raise click.ClickException(f"'{SHARED}' is reserved.")
        src_dirs = _profile_dirs(src)
        dst_dirs = _profile_dirs(dst)
        if not any(d.exists() for d in src_dirs.values()) and src != SHARED:
            raise click.ClickException(f"Source profile '{src}' does not exist.")
        if any(d.exists() for d in dst_dirs.values()):
            raise click.ClickException(f"Destination profile '{dst}' already exists.")
        for kind in src_dirs:
            if src_dirs[kind].exists():
                shutil.copytree(src_dirs[kind], dst_dirs[kind])
        click.echo(f"Cloned '{src}' → '{dst}'.")

    # ── delete ────────────────────────────────────────────────────────────
    @profile_cmd.command("delete")
    @click.argument("name")
    @click.option("--force", "-f", is_flag=True, help="Do not prompt for confirmation.")
    def profile_delete(name, force):
        """Delete a profile (config + data + cache). Cannot delete the active profile or _shared."""
        try:
            validate_profile_name(name)
        except ProfileError as exc:
            raise click.ClickException(str(exc))
        if name == SHARED:
            raise click.ClickException(f"'{SHARED}' is reserved and cannot be deleted here.")
        if name == resolve_profile():
            raise click.ClickException(
                f"'{name}' is the active profile. Switch away first: toolsetup profile use <other>"
            )
        dirs = _profile_dirs(name)
        existing = [d for d in dirs.values() if d.exists()]
        if not existing:
            raise click.ClickException(f"Profile '{name}' does not exist.")
        if not force:
            click.echo("Will delete:")
            for d in existing:
                click.echo(f"  {d}")
            click.confirm(f"Delete profile '{name}'?", abort=True)
        for d in existing:
            shutil.rmtree(d)
        click.echo(f"Deleted profile '{name}'.")

    # ── use ───────────────────────────────────────────────────────────────
    @profile_cmd.command("use")
    @click.argument("name")
    def profile_use(name):
        """Set NAME as the active profile (writes the active-profile pointer)."""
        try:
            write_active_pointer(name)
        except ProfileError as exc:
            raise click.ClickException(str(exc))
        if not _profile_dirs(name)["config"].exists():
            click.echo(f"Note: profile '{name}' has no config yet; create it with 'toolsetup profile create {name}'.")
        click.echo(f"Active profile is now '{name}'.")

    # ── migrate ───────────────────────────────────────────────────────────
    @profile_cmd.command("migrate")
    @click.option("--into", default="joriel", show_default=True, help="Target profile for the legacy layout.")
    @click.option("--force", "-f", is_flag=True, help="Proceed even if the target profile already exists.")
    @click.option("--dry-run", is_flag=True, help="Show what would move without moving anything.")
    def profile_migrate(into, force, dry_run):
        """Move a legacy (pre-profile) layout into a profile and activate it."""
        try:
            validate_profile_name(into)
        except ProfileError as exc:
            raise click.ClickException(str(exc))
        if into == SHARED:
            raise click.ClickException(f"'{SHARED}' is reserved.")

        roots = _roots()
        moved_any = False
        for kind, root in roots.items():
            if not root.exists():
                continue
            target = _profiles_dir(root) / into
            # Everything under the fast-market root except the profiles dir and pointer file.
            children = [
                c for c in root.iterdir()
                if c.name not in ("profiles", "active_profile")
            ]
            if not children:
                continue
            if target.exists() and not force and not dry_run:
                raise click.ClickException(
                    f"Target '{target}' already exists. Use --force to merge into it."
                )
            for child in children:
                dest = target / child.name
                moved_any = True
                if dry_run:
                    click.echo(f"  would move {child} → {dest}")
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    click.echo(f"  skip (exists): {dest}")
                    continue
                shutil.move(str(child), str(dest))
                click.echo(f"  moved {child.name} ({kind}) → {dest}")

        if dry_run:
            click.echo("Dry run complete; nothing moved.")
            return
        if not moved_any:
            click.echo("No legacy layout found to migrate.")
            return
        write_active_pointer(into)
        click.echo(f"\nMigrated legacy layout into profile '{into}' and set it active.")
        click.echo("Tip: promote shared things (e.g. the Anthropic key, workdir) into the "
                   f"'{SHARED}' base so other profiles inherit them.")

    return profile_cmd
