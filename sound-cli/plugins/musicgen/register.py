from __future__ import annotations

from plugins.base import PluginManifest
from plugins.musicgen.plugin import MusicGenModelPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="musicgen",
        engine_class=MusicGenModelPlugin,
        cli_options={},
        api_router=None,
    )
