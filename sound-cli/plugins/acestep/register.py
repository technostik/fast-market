from __future__ import annotations

from plugins.acestep.plugin import AcestepPlugin
from plugins.base import PluginManifest


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="acestep",
        engine_class=AcestepPlugin,
        cli_options={},
        api_router=None,
    )
