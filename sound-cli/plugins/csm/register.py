from __future__ import annotations

from plugins.base import PluginManifest
from plugins.csm.plugin import CsmPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="csm",
        engine_class=CsmPlugin,
        cli_options={},
        api_router=None,
    )
