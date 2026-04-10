from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.registry import discover_commands, discover_plugins

main = create_cli_group(
    "social",
    description="Post to and search across social media backends (Twitter, LinkedIn, Substack).",
)
_TOOL_ROOT = Path(__file__).resolve().parents[1]
_plugin_manifests = None


def _safe_discover_plugins(config: dict):
    """Discover plugins, tolerating missing/removed plugin directories."""
    import importlib
    from common.core.yaml_utils import dump_yaml  # noqa: F401 — ensure common is importable

    plugin_package = "plugins"
    plugin_root = _TOOL_ROOT / plugin_package
    if not plugin_root.is_dir():
        return {}

    manifests = {}
    for subdir in sorted(plugin_root.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith("_"):
            continue
        mod_path = f"{plugin_package}.{subdir.name}.register"
        try:
            mod = importlib.import_module(mod_path)
            manifest = mod.register(config)
            manifests[manifest.name] = manifest
        except ModuleNotFoundError:
            # Plugin directory was removed or is incomplete — skip gracefully
            logging.warning("Skipping plugin '%s': module not found", subdir.name)
        except Exception as e:
            logging.warning("Skipping plugin '%s': %s", subdir.name, e)
    return manifests


def _load() -> None:
    """Discover plugins and commands. Deferred config loading."""
    global _plugin_manifests
    logging.basicConfig(level=logging.CRITICAL, force=True)

    # Load config lazily — only when plugins are actually needed
    try:
        from core.config import load_config

        config = load_config()
    except Exception:
        # Allow CLI to start without config (for --help etc.)
        config = {}

    _plugin_manifests = _safe_discover_plugins(config)
    command_manifests = discover_commands(_plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


_load()
