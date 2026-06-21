from __future__ import annotations

from plugins.base import PluginManifest
from plugins.kokoro.plugin import KokoroPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="kokoro",
        engine_class=KokoroPlugin,
        cli_options={},
        api_router=None,
    )
