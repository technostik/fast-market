from plugins.base import PluginManifest
from plugins.flux29bcloud.plugin import Flux29bCloudEnginePlugin


def register(config: dict) -> PluginManifest:
    """Declare the flux29bcloud (FLUX.2 Klein-9B on Cloudflare) plugin."""
    return PluginManifest(
        name="flux29bcloud",
        engine_class=Flux29bCloudEnginePlugin,
        cli_options={},
        api_router=None,
    )
