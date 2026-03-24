from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import yaml

from common import structlog

logger = structlog.get_logger(__name__)

_MAX_ALIAS_DEPTH = 5

_aliases_cache: dict[str, dict] | None = None

AliasValue = dict[str, str] | str


def load_aliases(force_reload: bool = False) -> dict[str, dict]:
    """Load aliases from YAML config file with caching.

    Returns a dict mapping alias names to {command, description} dicts.
    Handles both old format (alias: command) and new format (alias: {command, description}).
    Handles missing/invalid files gracefully.
    """
    global _aliases_cache

    if _aliases_cache is not None and not force_reload:
        return _aliases_cache

    config_path = _get_aliases_path()

    if not config_path.exists():
        logger.debug(
            "aliases file not found, using empty aliases", path=str(config_path)
        )
        _aliases_cache = {}
        return _aliases_cache

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            logger.warning(
                "aliases file invalid format, expected mapping", path=str(config_path)
            )
            _aliases_cache = {}
            return _aliases_cache

        aliases = data.get("aliases", {})
        if not isinstance(aliases, dict):
            logger.warning(
                "aliases file invalid format, expected aliases mapping",
                path=str(config_path),
            )
            _aliases_cache = {}
            return _aliases_cache

        normalized: dict[str, dict] = {}
        for k, v in aliases.items():
            key = str(k)
            if isinstance(v, dict):
                normalized[key] = {
                    "command": str(v.get("command", "")),
                    "description": str(v.get("description", "")),
                }
            else:
                normalized[key] = {
                    "command": str(v),
                    "description": "",
                }
        _aliases_cache = normalized
        logger.debug("loaded aliases", count=len(_aliases_cache), path=str(config_path))
        return _aliases_cache

    except yaml.YAMLError as exc:
        logger.warning(
            "failed to parse aliases YAML, using empty aliases", error=str(exc)
        )
        _aliases_cache = {}
        return _aliases_cache


def save_aliases(aliases: dict[str, dict]) -> None:
    """Save aliases to YAML config file."""
    config_path = _get_aliases_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = {"aliases": aliases}
    yaml_content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    config_path.write_text(yaml_content, encoding="utf-8")

    global _aliases_cache
    _aliases_cache = aliases
    logger.debug("saved aliases", count=len(aliases), path=str(config_path))


def _get_aliases_path() -> Path:
    """Get the aliases config file path."""
    from common.core.paths import get_aliases_path

    return get_aliases_path()


def get_all_aliases() -> dict[str, dict]:
    """Get all aliases as a dict mapping name to {command, description}."""
    return load_aliases().copy()


def get_reverse_aliases() -> dict[str, list[str]]:
    """Map actual commands to their aliases.

    Returns a dict where keys are command strings and values are lists of alias names.
    """
    aliases = load_aliases()
    reverse: dict[str, list[str]] = {}

    for alias_name, alias_data in aliases.items():
        actual_cmd = alias_data["command"]
        if actual_cmd not in reverse:
            reverse[actual_cmd] = []
        reverse[actual_cmd].append(alias_name)

    return reverse


def resolve_alias(
    command_string: str, max_depth: int = _MAX_ALIAS_DEPTH
) -> tuple[str, str | None]:
    """Resolve an alias in a command string.

    If the first token is an alias, returns (resolved_command, alias_name).
    Otherwise returns (original_command, None).

    Detects circular aliases and prevents infinite loops.
    """
    if not command_string or max_depth <= 0:
        return command_string, None

    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return command_string, None

    if not tokens:
        return command_string, None

    first_token = tokens[0]
    aliases = load_aliases()

    if first_token not in aliases:
        return command_string, None

    alias_name = first_token
    actual_cmd = aliases[alias_name]["command"]

    logger.debug("resolving alias", alias=alias_name, resolved=actual_cmd)

    if len(tokens) == 1:
        return actual_cmd, alias_name

    remaining_args = shlex.join(tokens[1:])
    resolved_command = f"{actual_cmd} {remaining_args}"

    resolved_final, _ = resolve_alias(resolved_command, max_depth - 1)

    return resolved_final, alias_name


def expand_aliases_in_task(task: str) -> str:
    """Preprocess task string to expand aliases.

    This is an optional helper for preprocessing task descriptions.
    """
    resolved, _ = resolve_alias(task)
    return resolved


def get_aliases_for_command(command_name: str) -> list[str]:
    """Get all aliases that resolve to a specific command."""
    reverse = get_reverse_aliases()
    return reverse.get(command_name, [])


def create_or_update_alias(
    alias_name: str, actual_command: str, description: str | None = None
) -> bool:
    """Create or update an alias.

    Returns True if this was a new alias, False if updated.
    """
    aliases = load_aliases()
    is_new = alias_name not in aliases
    existing = aliases.get(alias_name, {})
    if isinstance(existing, str):
        existing = {"command": existing, "description": ""}
    aliases[alias_name] = {
        "command": actual_command,
        "description": description
        if description is not None
        else existing.get("description", ""),
    }
    save_aliases(aliases)
    return is_new


def get_alias_description(alias_name: str) -> str:
    """Get the description for an alias, or empty string if not found."""
    aliases = load_aliases()
    alias_data = aliases.get(alias_name, {})
    if isinstance(alias_data, str):
        return ""
    return alias_data.get("description", "")


def get_alias_command(alias_name: str) -> str:
    """Get the command for an alias, or empty string if not found."""
    aliases = load_aliases()
    alias_data = aliases.get(alias_name, {})
    if isinstance(alias_data, str):
        return alias_data
    return alias_data.get("command", "")


def remove_alias(alias_name: str) -> bool:
    """Remove an alias.

    Returns True if alias existed and was removed, False if not found.
    """
    aliases = load_aliases()
    if alias_name not in aliases:
        return False
    del aliases[alias_name]
    save_aliases(aliases)
    return True


def merge_aliases_from_file(file_path: Path) -> int:
    """Load aliases from a YAML file and merge with existing aliases.

    Returns the number of aliases loaded.
    """
    import yaml

    if not file_path.exists():
        raise FileNotFoundError(f"Alias file not found: {file_path}")

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in alias file: {exc}")

    if not isinstance(data, dict):
        raise ValueError("Alias file must contain a mapping")

    new_aliases = data.get("aliases", {})
    if not isinstance(new_aliases, dict):
        raise ValueError("Alias file must contain an 'aliases' mapping")

    current = load_aliases()
    for k, v in new_aliases.items():
        key = str(k)
        if isinstance(v, dict):
            current[key] = {
                "command": str(v.get("command", "")),
                "description": str(v.get("description", "")),
            }
        else:
            current[key] = {"command": str(v), "description": ""}
    save_aliases(current)

    return len(new_aliases)


def export_aliases() -> str:
    """Export all aliases as YAML string."""
    aliases = load_aliases()
    data = {"aliases": aliases}
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def get_alias_config_path() -> Path:
    """Get the path to the aliases config file."""
    return _get_aliases_path()
