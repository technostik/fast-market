from plugins.base.plugin import PluginManifest
from .plugin import BdorProvider
def register(config): return PluginManifest('bdor',BdorProvider,BdorProvider.descriptor)
