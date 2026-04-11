from __future__ import annotations

from pathlib import Path

import click
from click.shell_completion import CompletionItem

from common.core.config import load_tool_config


def _load_common_config() -> dict:
    """Load the common config directly."""
    from common.core.config import load_common_config
    return load_common_config()


def get_workdir() -> Path:
    """Get the configured workdir, falling back to workdir_root, then CWD."""
    try:
        config = _load_common_config()
        workdir = config.get("workdir")
        if workdir:
            return Path(workdir).expanduser().resolve()
        workdir_root = config.get("workdir_root")
        if workdir_root:
            return Path(workdir_root).expanduser().resolve()
    except Exception:
        pass
    return Path.cwd().resolve()


def get_workdir_root() -> Path | None:
    """Get the configured workdir_root, or None."""
    try:
        config = _load_common_config()
        workdir_root = config.get("workdir_root")
        if workdir_root:
            return Path(workdir_root).expanduser().resolve()
    except Exception:
        pass
    return None


_SCRIPT_EXTENSIONS = {".txt", ".sh", ".yml", ".yaml", ".md", ".browserscript"}


def _complete_dir(directory: Path, prefix: str) -> list[CompletionItem]:
    """Complete items in a directory, filtered by script extensions for files."""
    items = []
    for item in sorted(directory.iterdir()):
        if prefix and not item.name.lower().startswith(prefix.lower()):
            continue
        if item.is_dir():
            items.append(CompletionItem(str(item) + "/", help="Directory"))
        elif item.is_file():
            if (
                not prefix
                or item.suffix.lower() in _SCRIPT_EXTENSIONS
                or not item.suffix
            ):
                items.append(CompletionItem(str(item), help="Script file"))
    return items


class ScriptPathParamType(click.ParamType):
    """Completes script file paths from workdir then workdir_root."""

    name = "script_file"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        try:
            path = Path(incomplete) if incomplete else Path("")

            if path.is_absolute():
                # Absolute path: complete from filesystem as-is
                parent = path.parent if path.name else path
                prefix = path.name if path.name else ""
            elif incomplete.startswith("~"):
                expanded = path.expanduser()
                parent = expanded.parent if expanded.name else expanded
                prefix = expanded.name if expanded.name else ""
            else:
                # Relative path: prefix from what user typed
                parent = None
                prefix = path.name if path.name else ""

            if parent is not None and parent.exists():
                return _complete_dir(parent, prefix)

            # Relative path: search from workdir, then workdir_root
            items = []
            workdir = get_workdir()
            if workdir.exists() and workdir != Path.cwd().resolve():
                items.extend(_complete_dir(workdir, prefix))

            workdir_root = get_workdir_root()
            if workdir_root and workdir_root.exists() and workdir_root != workdir and workdir_root != Path.cwd().resolve():
                items.extend(_complete_dir(workdir_root, prefix))

            return items[:50]
        except (PermissionError, OSError):
            return []

    def convert(self, value, param, ctx):
        return value


def resolve_script_path(value: str) -> Path | None:
    """Resolve a script file path.

    Search order for relative paths:
    1. Absolute or ~ expanded path
    2. CWD
    3. workdir (from common config)
    4. workdir_root (from common config)
    """
    p = Path(value)

    if p.is_absolute() and p.exists():
        return p

    if value.startswith("~"):
        expanded = p.expanduser()
        if expanded.exists():
            return expanded
        return None

    # Relative path: check CWD first
    if p.exists():
        return p.resolve()

    # Then workdir (which already falls back to workdir_root)
    workdir = get_workdir()
    if workdir != Path.cwd().resolve():
        candidate = workdir / p
        if candidate.exists():
            return candidate.resolve()

    # Explicitly check workdir_root if different from workdir
    workdir_root = get_workdir_root()
    if workdir_root and workdir_root != workdir and workdir_root != Path.cwd().resolve():
        candidate = workdir_root / p
        if candidate.exists():
            return candidate.resolve()

    return None
