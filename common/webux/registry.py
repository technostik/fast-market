from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable

from common import structlog
from common.webux.base import WebuxPluginManifest

logger = structlog.get_logger(__name__)


def _validate_and_add(
    discovered: dict[str, WebuxPluginManifest],
    manifest: WebuxPluginManifest,
    source_name: str,
) -> None:
    if not isinstance(manifest, WebuxPluginManifest):
        raise TypeError(
            f"FAIL LOUDLY: webux plugin '{source_name}' register() must return "
            f"WebuxPluginManifest, got {type(manifest)}"
        )

    if manifest.name in discovered:
        raise RuntimeError(
            f"FAIL LOUDLY: duplicate webux plugin name '{manifest.name}' "
            f"from '{source_name}'"
        )

    discovered[manifest.name] = manifest
    logger.info("webux_plugin_registered", name=manifest.name, lazy=manifest.lazy)


def _discover_from_entry_points(config: dict) -> dict[str, WebuxPluginManifest]:
    from importlib.metadata import entry_points

    discovered: dict[str, WebuxPluginManifest] = {}
    for ep in entry_points(group="fast_market.webux_plugins"):
        logger.debug("webux_plugin_loading", entry_point=ep.name, value=ep.value)
        try:
            register_fn: Callable = ep.load()
        except Exception as exc:
            raise RuntimeError(
                f"FAIL LOUDLY: Failed to load webux plugin entry point '{ep.name}': {exc}"
            ) from exc

        try:
            manifest = register_fn(config)
        except Exception as exc:
            raise RuntimeError(
                f"FAIL LOUDLY: register() raised in webux plugin '{ep.name}': {exc}"
            ) from exc

        _validate_and_add(discovered, manifest, ep.name)

    return discovered


def _discover_from_repo_layout(config: dict) -> dict[str, WebuxPluginManifest]:
    """Discover plugins from local monorepo layout: */webux/*/register.py."""
    discovered: dict[str, WebuxPluginManifest] = {}
    repo_root = Path(__file__).resolve().parents[2]

    for cli_dir in sorted(repo_root.glob("*-cli")):
        webux_dir = cli_dir / "webux"
        if not webux_dir.is_dir():
            continue
        for register_path in sorted(webux_dir.glob("*/register.py")):
            plugin_key = f"{cli_dir.name}:{register_path.parent.name}"
            module_name = (
                f"fast_market_dynamic_webux_{cli_dir.name.replace('-', '_')}_"
                f"{register_path.parent.name}_register"
            )
            logger.debug(
                "webux_plugin_loading_repo",
                plugin=plugin_key,
                path=str(register_path),
            )
            try:
                spec = importlib.util.spec_from_file_location(module_name, register_path)
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"cannot create module spec for {register_path}")
                module = importlib.util.module_from_spec(spec)
                sys.path.insert(0, str(cli_dir))
                try:
                    spec.loader.exec_module(module)
                finally:
                    sys.path.pop(0)
            except Exception as exc:
                raise RuntimeError(
                    f"FAIL LOUDLY: Failed to import webux plugin module '{plugin_key}': {exc}"
                ) from exc

            if not hasattr(module, "register"):
                raise RuntimeError(
                    f"FAIL LOUDLY: webux plugin '{plugin_key}' has no register(config)"
                )

            try:
                manifest = module.register(config)
            except Exception as exc:
                raise RuntimeError(
                    f"FAIL LOUDLY: register() raised in webux plugin '{plugin_key}': {exc}"
                ) from exc

            _validate_and_add(discovered, manifest, plugin_key)

    return discovered


def discover_webux_plugins(config: dict) -> dict[str, WebuxPluginManifest]:
    """Discover webux plugins via entry points, with monorepo fallback discovery."""
    try:
        from importlib.metadata import entry_points  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("importlib.metadata unavailable — requires Python 3.9+") from exc

    discovered = _discover_from_entry_points(config)
    if not discovered:
        logger.info("webux_plugin_entry_points_empty_fallback_to_repo_layout")
        discovered = _discover_from_repo_layout(config)

    return dict(sorted(discovered.items(), key=lambda kv: (kv[1].order, kv[0])))
