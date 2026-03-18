from __future__ import annotations

import sys
from datetime import datetime

import click

from commands.base import CommandManifest
from common.cli.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    provider_choices = list(plugin_manifests.keys()) if plugin_manifests else []

    @click.command("apply")
    @click.argument("prompt_name")
    @click.option("--provider", type=click.Choice(provider_choices) if provider_choices else str, default=None)
    @click.option("--model", default=None)
    @click.option("--temperature", type=float, default=None)
    @click.option("--max-tokens", type=int, default=None)
    @click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def apply_cmd(ctx, prompt_name, provider, model, temperature, max_tokens, fmt, args):
        """Apply a prompt with placeholder substitution."""
        from common.core.config import load_tool_config
        from commands.helpers import build_engine, get_default_provider
        from core.models import PromptExecution
        from core.substitution import resolve_arguments
        from plugins.base import LLMRequest
        from storage.store import PromptStore

        store = PromptStore()
        prompt = store.get_prompt(prompt_name)
        if not prompt:
            click.echo(f"Prompt not found: {prompt_name}", err=True)
            sys.exit(1)

        placeholder_args: dict[str, str] = {}
        for arg in args:
            if "=" not in arg:
                click.echo(f"Invalid argument: {arg} (expected key=value)", err=True)
                sys.exit(1)
            key, value = arg.split("=", 1)
            placeholder_args[key] = value

        try:
            resolved = resolve_arguments(prompt.content, placeholder_args)
        except (FileNotFoundError, ValueError) as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

        config = load_tool_config("prompt")
        provider_name = provider or prompt.model_provider or get_default_provider(config)
        providers = build_engine(ctx.obj["verbose"])
        if provider_name not in providers:
            click.echo(f"Provider not found: {provider_name}", err=True)
            click.echo(f"Run 'prompt setup --add-provider {provider_name}' first", err=True)
            sys.exit(1)

        request = LLMRequest(
            prompt=resolved,
            model=model or prompt.model_name or None,
            temperature=temperature if temperature is not None else prompt.temperature,
            max_tokens=max_tokens or prompt.max_tokens,
        )
        response = providers[provider_name].complete(request)
        store.record_execution(
            PromptExecution(
                prompt_name=prompt_name,
                input_args=placeholder_args,
                resolved_content=resolved,
                output=response.content,
                model_provider=provider_name,
                model_name=response.model,
                timestamp=datetime.utcnow(),
                metadata=response.metadata or {},
            )
        )

        if fmt == "json":
            out(
                {
                    "prompt_name": prompt_name,
                    "output": response.content,
                    "model": response.model,
                    "usage": response.usage,
                },
                fmt,
            )
            return
        click.echo(response.content)

    return CommandManifest(name="apply", click_command=apply_cmd)
