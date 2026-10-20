from plugins.base import PluginManifest
from plugins.flux3.plugin import Flux3EnginePlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="flux3",
        engine_class=Flux3EnginePlugin,
        cli_options={},
        api_router=None,
    )
