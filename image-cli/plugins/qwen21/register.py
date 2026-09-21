from plugins.base import PluginManifest
from plugins.qwen21.plugin import Qwen21EnginePlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the qwen21 plugin contributes to the system."""
    return PluginManifest(
        name="qwen21",
        engine_class=Qwen21EnginePlugin,
        cli_options={},
        api_router=None,
    )
