from __future__ import annotations

from common.llm.base import PluginManifest
from common.llm.openai.provider import OpenAIProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="openai", provider_class=OpenAIProvider)
