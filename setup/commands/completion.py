from __future__ import annotations

import click
from click.shell_completion import CompletionItem

from common.core.config import load_llm_config


class ProviderParamType(click.ParamType):
    name = "provider"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        config = load_llm_config()
        providers = config.get("providers", {})
        return [
            CompletionItem(name)
            for name in sorted(providers.keys())
            if incomplete.lower() in name.lower()
        ]


class AvailableProviderParamType(click.ParamType):
    name = "available_provider"

    AVAILABLE = {
        "anthropic",
        "openai",
        "openai-compatible",
        "ollama",
    }

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        return [
            CompletionItem(name)
            for name in sorted(self.AVAILABLE)
            if incomplete.lower() in name.lower()
        ]
