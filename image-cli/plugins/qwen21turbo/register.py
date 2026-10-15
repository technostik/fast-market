from plugins.base import PluginManifest
from plugins.qwen21turbo.plugin import Qwen21TurboEnginePlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the qwen21turbo plugin contributes to the system."""
    return PluginManifest(
        name="qwen21turbo",
        engine_class=Qwen21TurboEnginePlugin,
        cli_options={},
        api_router=None,
    )
