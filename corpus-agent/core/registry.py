from __future__ import annotations

import importlib
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


def discover_plugins(config: dict) -> dict[str, "PluginManifest"]:
    """
    Scan plugins/ for subdirectories containing register.py.
    Call register(config) -> PluginManifest for each.
    Fail loudly if register() is missing or raises.
    Skip __pycache__ and any dir starting with '_'.
    """
    from plugins.base import PluginManifest

    plugins_dir = _ROOT / "plugins"
    manifests: dict[str, PluginManifest] = {}

    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        mod_path = f"plugins.{entry.name}.register"
        try:
            mod = importlib.import_module(mod_path)
        except ModuleNotFoundError:
            # No register.py yet — skip silently during transition.
            # Once all plugins have register.py this should become a hard error.
            continue
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
) -> dict[str, "CommandManifest"]:
    """
    Scan commands/ for subdirectories containing register.py.
    Call register(plugin_manifests) -> CommandManifest for each.
    Returns empty dict if commands/ directory does not exist yet.
    Fail loudly if register() exists but raises or returns wrong type.
    """
    from commands.base import CommandManifest

    commands_dir = _ROOT / "commands"
    if not commands_dir.exists():
        return {}

    manifests: dict[str, CommandManifest] = {}
    pm = plugin_manifests or {}

    for entry in sorted(commands_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        mod_path = f"commands.{entry.name}.register"
        try:
            mod = importlib.import_module(mod_path)
        except ModuleNotFoundError:
            continue
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


def build_plugins(config: dict) -> dict[str, object]:
    """
    Backward-compatible builder used by cli/main.py and api/server.py today.
    Tries discover_plugins() first; falls back to direct instantiation if a
    plugin has no register.py yet (transition period only).
    """
    try:
        manifests = discover_plugins(config)
        if manifests:
            return {
                name: manifest.source_plugin_class(config)
                for name, manifest in manifests.items()
            }
    except Exception as exc:
        logger.error("discover_plugins_failed", error=str(exc))
        raise

    # Fallback: direct instantiation (remove once all register.py files exist)
    from plugins.obsidian.plugin import ObsidianPlugin
    from plugins.youtube.plugin import YouTubePlugin

    return {
        "obsidian": ObsidianPlugin(config),
        "youtube": YouTubePlugin(config),
    }
