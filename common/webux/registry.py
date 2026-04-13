from __future__ import annotations

from typing import Callable

from common import structlog
from common.webux.base import WebuxPluginManifest

logger = structlog.get_logger(__name__)


def discover_webux_plugins(config: dict) -> dict[str, WebuxPluginManifest]:
    """Auto-discover all installed fast-market webux plugins via entry points."""
    try:
        from importlib.metadata import entry_points
    except ImportError as exc:
        raise RuntimeError("importlib.metadata unavailable — requires Python 3.9+") from exc

    eps = entry_points(group="fast_market.webux_plugins")
    discovered: dict[str, WebuxPluginManifest] = {}

    for ep in eps:
        logger.debug("webux_plugin_loading", entry_point=ep.name, value=ep.value)
        try:
            register_fn: Callable = ep.load()
        except Exception as exc:
            raise RuntimeError(
                f"FAIL LOUDLY: Failed to load webux plugin entry point '{ep.name}': {exc}"
            ) from exc

        try:
            manifest: WebuxPluginManifest = register_fn(config)
        except Exception as exc:
            raise RuntimeError(
                f"FAIL LOUDLY: register() raised in webux plugin '{ep.name}': {exc}"
            ) from exc

        if not isinstance(manifest, WebuxPluginManifest):
            raise TypeError(
                f"FAIL LOUDLY: webux plugin '{ep.name}' register() must return "
                f"WebuxPluginManifest, got {type(manifest)}"
            )

        if manifest.name in discovered:
            raise RuntimeError(
                f"FAIL LOUDLY: duplicate webux plugin name '{manifest.name}' "
                f"from entry point '{ep.name}'"
            )

        discovered[manifest.name] = manifest
        logger.info("webux_plugin_registered", name=manifest.name, lazy=manifest.lazy)

    return dict(sorted(discovered.items(), key=lambda kv: (kv[1].order, kv[0])))
