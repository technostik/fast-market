from plugins.base.plugin import PluginManifest
from .plugin import YahooProvider
def register(config): return PluginManifest('yahoo',YahooProvider,YahooProvider.descriptor)
