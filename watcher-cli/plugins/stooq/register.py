from plugins.base.plugin import PluginManifest
from .plugin import StooqProvider
def register(config): return PluginManifest('stooq',StooqProvider,StooqProvider.descriptor)
