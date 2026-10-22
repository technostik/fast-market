from plugins.base.plugin import PluginManifest
from .plugin import EconomieProvider
def register(config): return PluginManifest("economie", EconomieProvider, EconomieProvider.descriptor)
