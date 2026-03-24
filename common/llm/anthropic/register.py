from __future__ import annotations

from common.llm.anthropic.provider import AnthropicProvider
from common.llm.base import PluginManifest


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="anthropic", provider_class=AnthropicProvider)
