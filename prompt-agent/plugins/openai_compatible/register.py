from __future__ import annotations

from plugins.base import PluginManifest
from plugins.openai_compatible.plugin import OpenAICompatibleProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="openai-compatible", provider_class=OpenAICompatibleProvider)
