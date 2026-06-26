"""Active-profile resolution for multi-persona support.

A *profile* is a directory namespace under each XDG root. Every path in
``common.core.paths`` is scoped to the active profile, so config, data and cache
isolate per persona at once.

Resolution order (first match wins):
    1. ``FASTMARKET_PROFILE`` environment variable (set by the ``--profile`` flag
       in ``common.cli.base`` or exported manually)
    2. ``~/.config/fast-market/active_profile`` pointer file
    3. fallback constant :data:`DEFAULT_PROFILE`

``_shared`` is a reserved profile: it is the inheritance base searched in
addition to the active profile, and it is never itself "active".
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Reserved profile name used as the inheritance / shared-resource base.
SHARED = "_shared"

#: Fallback profile name when nothing else selects one. Not auto-created.
DEFAULT_PROFILE = "default"

#: Environment variable that pins the active profile for a process.
ENV_VAR = "FASTMARKET_PROFILE"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_RESERVED = {SHARED}


class ProfileError(Exception):
    """Raised for an invalid profile name or selection."""


def validate_profile_name(name: str) -> str:
    """Return ``name`` if it is a valid profile slug, else raise ProfileError."""
    if not name or not _NAME_RE.match(name):
        raise ProfileError(
            f"Invalid profile name {name!r}: use lowercase letters, digits, "
            "'-' or '_', starting with a letter or digit."
        )
    return name


def _active_profile_pointer() -> Path:
    """``~/.config/fast-market/active_profile`` (independent of the active profile)."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "fast-market" / "active_profile"


def read_active_pointer() -> str | None:
    """Return the profile written in the pointer file, or None if unset."""
    pointer = _active_profile_pointer()
    if not pointer.exists():
        return None
    name = pointer.read_text(encoding="utf-8").strip()
    return name or None


def write_active_pointer(name: str) -> None:
    """Persist ``name`` as the active profile in the pointer file."""
    validate_profile_name(name)
    if name in _RESERVED:
        raise ProfileError(f"{name!r} is reserved and cannot be the active profile.")
    pointer = _active_profile_pointer()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(name + "\n", encoding="utf-8")


def resolve_profile() -> str:
    """Resolve the active profile name (read fresh on every call).

    Read fresh rather than cached so that environment / pointer changes within a
    process (notably in tests) take effect immediately.
    """
    env = os.environ.get(ENV_VAR)
    if env:
        name = env.strip()
        if name:
            validate_profile_name(name)
            if name in _RESERVED:
                raise ProfileError(f"{name!r} is reserved and cannot be active.")
            return name

    pointer = read_active_pointer()
    if pointer:
        validate_profile_name(pointer)
        if pointer in _RESERVED:
            raise ProfileError(f"{pointer!r} is reserved and cannot be active.")
        return pointer

    return DEFAULT_PROFILE
