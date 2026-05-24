from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path


def _find_repo_root() -> Path:
    """Locate the fast-market monorepo root by walking up from this file.

    Looks for a directory containing both 'common/' and 'AGENTS.md'.
    This is internal to toolsetup only.
    """
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / "common").is_dir() and (parent / "AGENTS.md").exists():
            return parent
    raise RuntimeError(
        "FAIL LOUDLY: Could not locate fast-market monorepo root.\n"
        "toolsetup auto-discovery requires running inside a checkout that has "
        "'common/' and top-level 'AGENTS.md'.\n"
        "Run from within the fast-market source tree."
    )


@cache
def discover_fastmarket_commands() -> list[str]:
    """Auto-discover every fast-market top-level CLI command name.

    Only used by toolsetup (autocomplete + setup init).
    Scans all *-cli/pyproject.toml files under the monorepo root and
    returns the sorted list of keys found under [project.scripts].
    No hardcoded fallback — pure discovery.
    """
    root = _find_repo_root()
    names: set[str] = set()

    for pyproj in sorted(root.glob("*-cli/pyproject.toml")):
        try:
            with pyproj.open("rb") as f:
                data = tomllib.load(f)
            scripts = data.get("project", {}).get("scripts", {})
            if isinstance(scripts, dict):
                names.update(scripts.keys())
        except Exception as exc:
            raise RuntimeError(
                f"FAIL LOUDLY: Failed to read or parse {pyproj} during command discovery: {exc}"
            ) from exc

    if not names:
        raise RuntimeError(
            "FAIL LOUDLY: No *-cli directories with [project.scripts] entries found in the monorepo."
        )

    return sorted(names)
