from plugins.base.plugin import PluginManifest
from .plugin import BdfProvider
def register(config): return PluginManifest('bdf',BdfProvider,BdfProvider.descriptor)
