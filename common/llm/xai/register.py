from __future__ import annotations

from common.llm.base import PluginManifest
from common.llm.xai.provider import XAIProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="xai", provider_class=XAIProvider)
