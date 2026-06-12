from plugins.base import PluginManifest
from plugins.flux2cloud.plugin import Flux2CloudEnginePlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the flux2cloud plugin contributes to the system."""
    return PluginManifest(
        name="flux2cloud",
        engine_class=Flux2CloudEnginePlugin,
        cli_options={},
        api_router=None,
    )
