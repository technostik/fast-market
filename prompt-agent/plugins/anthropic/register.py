from __future__ import annotations

from plugins.anthropic.plugin import AnthropicProvider
from plugins.base import PluginManifest


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="anthropic", provider_class=AnthropicProvider)
