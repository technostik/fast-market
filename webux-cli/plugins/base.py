# Compatibility shim — new code should import from common.webux.base directly.
from common.webux.base import WebuxPluginManifest as PluginManifest

__all__ = ["PluginManifest"]
