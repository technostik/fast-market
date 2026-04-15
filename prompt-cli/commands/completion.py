from __future__ import annotations

import click
from click.shell_completion import CompletionItem


class PromptNameParamType(click.ParamType):
    name = "prompt_name"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        from storage.store import PromptStore

        store = PromptStore()
        prompts = store.list_prompts()

        completions = []
        for prompt in prompts:
            if prompt.name.lower().startswith(incomplete.lower()):
                desc = f" - {prompt.description}" if prompt.description else ""
                completions.append(CompletionItem(prompt.name, help=desc))

        return completions

    def get_completion_class(self):
        return None
