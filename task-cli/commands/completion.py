from __future__ import annotations

import click
from click.shell_completion import CompletionItem


class ProviderParamType(click.ParamType):
    name = "provider"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        try:
            from common.core.config import load_tool_config, ConfigError
            from common.llm.registry import discover_providers

            config = load_tool_config("apply")
            providers = discover_providers(config)

            completions = []
            for name in providers.keys():
                if incomplete.lower() in name.lower():
                    completions.append(CompletionItem(name, help=f"Provider: {name}"))

            return completions
        except ConfigError:
            return []

    def get_completion_class(self):
        return None
