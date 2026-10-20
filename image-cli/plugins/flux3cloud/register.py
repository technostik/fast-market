from plugins.base import PluginManifest
from plugins.flux3cloud.plugin import Flux3CloudEnginePlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="flux3cloud",
        engine_class=Flux3CloudEnginePlugin,
        cli_options={},
        api_router=None,
    )
