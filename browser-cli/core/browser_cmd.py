from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


_COMMAND_FILE = "COMMAND.md"

_COMMAND_TEMPLATE = """\
---
name: {name}
description:
parameters: []
---
# Browser script instructions — one agent-browser command per line.
# Use {{param_name}} for parameter substitution.
# Example:
#   navigate https://example.com
#   click @login-button
#   type @username {{greeting}}
"""


@dataclass(slots=True)
class BrowserCmd:
    """A stored browser command, loaded from a COMMAND.md file."""

    name: str
    path: Path
    description: str = ""
    parameters: list[dict] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: Path) -> Optional["BrowserCmd"]:
        cmd_file = path / _COMMAND_FILE
        if not cmd_file.exists():
            return None

        content = cmd_file.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1])
                    if frontmatter is None:
                        frontmatter = {}
                    raw_params = frontmatter.get("parameters") or []
                    parameters = [
                        p if isinstance(p, dict) else {"name": str(p), "description": "", "required": True}
                        for p in raw_params
                    ]
                    return cls(
                        name=frontmatter.get("name", path.name),
                        path=path,
                        description=frontmatter.get("description", "") or "",
                        parameters=parameters,
                    )
                except Exception:
                    pass

        return cls(name=path.name, path=path, description="")

    def get_body(self) -> str:
        """Return the script body (everything after the frontmatter block)."""
        content = (self.path / _COMMAND_FILE).read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content.strip()

    def get_instructions(self) -> list[str]:
        """Return non-empty, non-comment lines from the body."""
        lines = []
        for line in self.get_body().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "#" in stripped:
                stripped = stripped.split("#", 1)[0].strip()
            if stripped:
                lines.append(stripped)
        return lines


def discover_browser_cmds(cmds_dir: Path) -> list[BrowserCmd]:
    """Discover all browser commands in the given directory."""
    if not cmds_dir.exists():
        return []

    cmds = []
    for item in sorted(cmds_dir.iterdir()):
        if item.is_dir():
            cmd = BrowserCmd.from_path(item)
            if cmd:
                cmds.append(cmd)
    return cmds


def discover_browser_cmds_layered(search_dirs: list[Path] | None = None) -> list[BrowserCmd]:
    """Discover browser commands across the active profile then the _shared base.

    A command in the profile shadows a shared command of the same name.
    """
    if search_dirs is None:
        from common.core.paths import get_browser_cmds_search_dirs

        search_dirs = get_browser_cmds_search_dirs()

    seen: set[str] = set()
    cmds: list[BrowserCmd] = []
    for cmds_dir in search_dirs:
        if not cmds_dir.exists():
            continue
        for item in sorted(cmds_dir.iterdir()):
            if item.is_dir() and item.name not in seen:
                cmd = BrowserCmd.from_path(item)
                if cmd:
                    seen.add(item.name)
                    cmds.append(cmd)
    return cmds


def resolve_browser_cmd_dir(name: str, search_dirs: list[Path] | None = None) -> Path | None:
    """Return a browser command's dir, searching the profile then _shared. None if absent."""
    if search_dirs is None:
        from common.core.paths import get_browser_cmds_search_dirs

        search_dirs = get_browser_cmds_search_dirs()
    for cmds_dir in search_dirs:
        candidate = cmds_dir / name
        if candidate.is_dir():
            return candidate
    return None
