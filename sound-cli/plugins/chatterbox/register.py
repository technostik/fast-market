from __future__ import annotations

from plugins.base import PluginManifest
from plugins.chatterbox.plugin import ChatterboxTTSPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="chatterbox",
        engine_class=ChatterboxTTSPlugin,
        cli_options={},
        api_router=None,
    )
