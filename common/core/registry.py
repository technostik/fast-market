from __future__ import annotations

import importlib
from pathlib import Path

from common import structlog

logger = structlog.get_logger(__name__)


def _resolve_tool_root(tool_root: str | Path | None) -> Path:
    if tool_root is None:
        raise RuntimeError("FAIL LOUDLY: tool_root is required for common registry discovery")
    return Path(tool_root).expanduser().resolve()


def discover_plugins(
    config: dict,
    *,
    tool_root: str | Path | None,
    plugin_package: str = "plugins",
) -> dict[str, "PluginManifest"]:
    """Discover plugin manifests for the given tool root."""
    from plugins.base import PluginManifest

    plugins_dir = _resolve_tool_root(tool_root) / "plugins"
    manifests: dict[str, PluginManifest] = {}

    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if not (entry / "register.py").exists():
            continue
        mod_path = f"{plugin_package}.{entry.name}.register"
        mod = importlib.import_module(mod_path)
        if not hasattr(mod, "register"):
            raise RuntimeError(
                f"FAIL LOUDLY: {mod_path} exists but has no register() function"
            )
        manifest: PluginManifest = mod.register(config)
        if not isinstance(manifest, PluginManifest):
            raise TypeError(
                f"FAIL LOUDLY: {mod_path}.register() must return PluginManifest, "
                f"got {type(manifest)}"
            )
        manifests[manifest.name] = manifest

    return manifests


def discover_commands(
    plugin_manifests: dict | None = None,
    *,
    tool_root: str | Path | None,
    command_package: str = "commands",
) -> dict[str, "CommandManifest"]:
    """Discover command manifests for the given tool root."""
    from commands.base import CommandManifest

    commands_dir = _resolve_tool_root(tool_root) / "commands"
    if not commands_dir.exists():
        return {}

    manifests: dict[str, CommandManifest] = {}
    pm = plugin_manifests or {}

    for entry in sorted(commands_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if not (entry / "register.py").exists():
            continue
        mod_path = f"{command_package}.{entry.name}.register"
        mod = importlib.import_module(mod_path)
        if not hasattr(mod, "register"):
            raise RuntimeError(
                f"FAIL LOUDLY: {mod_path} exists but has no register() function"
            )
        manifest: CommandManifest = mod.register(pm)
        if not isinstance(manifest, CommandManifest):
            raise TypeError(
                f"FAIL LOUDLY: {mod_path}.register() must return CommandManifest, "
                f"got {type(manifest)}"
            )
        manifests[manifest.name] = manifest

    return manifests


def build_plugins(
    config: dict,
    *,
    tool_root: str | Path | None,
    plugin_package: str = "plugins",
) -> dict[str, object]:
    """Build source plugin instances from discovered manifests."""
    try:
        manifests = discover_plugins(config, tool_root=tool_root, plugin_package=plugin_package)
        if manifests:
            return {
                name: manifest.source_plugin_class(config)
                for name, manifest in manifests.items()
            }
    except Exception as exc:
        logger.error("discover_plugins_failed", error=str(exc))
        raise
    return {}
