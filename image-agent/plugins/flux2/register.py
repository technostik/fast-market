from plugins.base import PluginManifest
from plugins.flux2.plugin import Flux2EnginePlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the flux2 plugin contributes to the system."""
    return PluginManifest(
        name="flux2",
        engine_class=Flux2EnginePlugin,
        cli_options={},
        api_router=None,
    )
