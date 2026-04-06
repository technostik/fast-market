from __future__ import annotations

import sys
from datetime import datetime

import click

from commands.base import CommandManifest
from commands.completion import PromptNameParamType
from common.cli.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    provider_choices = list(plugin_manifests.keys()) if plugin_manifests else []

    @click.command("apply")
    @click.argument("prompt_name_or_content", type=PromptNameParamType())
    @click.option(
        "--provider",
        "-P",
        type=click.Choice(provider_choices) if provider_choices else str,
        default=None,
    )
    @click.option("--model", "-m", default=None)
    @click.option("--temperature", "-T", type=float, default=None)
    @click.option("--max-tokens", "-M", type=int, default=None)
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["text", "json"]), default="text"
    )
    @click.option(
        "--stdin",
        "-s",
        is_flag=True,
        help="Read prompt content from stdin (for piping)",
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def apply_cmd(
        ctx,
        prompt_name_or_content,
        provider,
        model,
        temperature,
        max_tokens,
        fmt,
        stdin,
        args,
    ):
        """Apply a prompt with placeholder substitution.

        PROMPT_NAME_OR_CONTENT can be:
        - A saved prompt name (e.g., 'summarize')
        - A direct prompt string (e.g., "Explain {topic}")
        - "-" to read from stdin (or use --stdin flag)

        Examples:
          prompt apply summarize text=@article.txt
          prompt apply "Explain {topic}" topic="quantum physics"
          echo "What is AI?" | prompt apply -
          cat prompt.txt | prompt apply --stdin
        """
        from common.core.config import load_tool_config
        from commands.helpers import build_engine, get_default_provider
        from core.models import PromptExecution
        from core.substitution import resolve_arguments
        from common.llm.base import LLMRequest
        from storage.store import PromptStore

        # Determine if this is a direct prompt or a saved prompt
        is_direct_prompt = False
        prompt_content = None
        saved_prompt = None

        # Read from stdin if requested
        if stdin or prompt_name_or_content == "-":
            # Check if this is a named prompt (not "-")
            if stdin and prompt_name_or_content != "-":
                # User provided a named prompt with --stdin flag
                # Try to load the saved prompt to show its placeholders
                store = PromptStore()
                maybe_saved_prompt = store.get_prompt(prompt_name_or_content)

                if maybe_saved_prompt:
                    from core.substitution import extract_placeholders

                    placeholders = extract_placeholders(maybe_saved_prompt.content)
                    if placeholders:
                        placeholder_list = " ".join(
                            f"{p}=-" for p in placeholders
                        )
                        click.echo(
                            f"Error: --stdin is not compatible with applying a named prompt.\n"
                            f"Named prompt '{prompt_name_or_content}' has placeholders: {', '.join(placeholders)}\n"
                            f"Instead use: prompt apply {prompt_name_or_content} {placeholder_list}",
                            err=True,
                        )
                    else:
                        click.echo(
                            f"Error: --stdin is not compatible with applying a named prompt.\n"
                            f"Instead use: prompt apply {prompt_name_or_content}",
                            err=True,
                        )
                    sys.exit(1)
                # If not a saved prompt, treat as direct prompt + stdin (allowed, stdin overrides)

            if not sys.stdin.isatty():
                prompt_content = sys.stdin.read().strip()
                if not prompt_content:
                    click.echo("Error: No input from stdin", err=True)
                    sys.exit(1)
                is_direct_prompt = True
                prompt_name_or_content = "<stdin>"
            else:
                click.echo(
                    "Error: No stdin available (pipe content into this command)",
                    err=True,
                )
                sys.exit(1)
        else:
            # Try to load as saved prompt first
            store = PromptStore()
            saved_prompt = store.get_prompt(prompt_name_or_content)

            if saved_prompt:
                prompt_content = saved_prompt.content
            else:
                # Treat as direct prompt
                is_direct_prompt = True
                prompt_content = prompt_name_or_content

        # Parse placeholder arguments
        placeholder_args: dict[str, str] = {}
        for arg in args:
            if "=" not in arg:
                click.echo(f"Invalid argument: {arg} (expected key=value)", err=True)
                sys.exit(1)
            key, value = arg.split("=", 1)
            placeholder_args[key] = value

        # Resolve placeholders in the prompt
        try:
            resolved = resolve_arguments(prompt_content, placeholder_args)
        except (FileNotFoundError, ValueError) as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

        # Determine provider and model settings
        config = load_tool_config("prompt")
        if saved_prompt:
            provider_name = (
                provider or saved_prompt.model_provider or get_default_provider(config)
            )
            model_name = model or saved_prompt.model_name or None
            temp = temperature if temperature is not None else saved_prompt.temperature
            max_tok = max_tokens or saved_prompt.max_tokens
        else:
            provider_name = provider or get_default_provider(config)
            model_name = model
            temp = temperature
            max_tok = max_tokens

        # Build provider engine
        providers = build_engine(ctx.obj["verbose"])
        if provider_name not in providers:
            click.echo(f"Provider not found: {provider_name}", err=True)
            click.echo(
                f"Run 'prompt setup providers add {provider_name}' first", err=True
            )
            sys.exit(1)

        # Execute the prompt
        request = LLMRequest(
            prompt=resolved,
            model=model_name,
            temperature=temp,
            max_tokens=max_tok,
        )
        try:
            response = providers[provider_name].complete(request)
        except RuntimeError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        except Exception as exc:
            click.echo(f"Error: {provider_name} provider failed: {exc}", err=True)
            sys.exit(1)

        # Record execution (only for saved prompts or with a meaningful identifier)
        execution_name = prompt_name_or_content if not is_direct_prompt else "<direct>"
        store = PromptStore()
        store.record_execution(
            PromptExecution(
                prompt_name=execution_name,
                input_args=placeholder_args,
                resolved_content=resolved,
                output=response.content,
                model_provider=provider_name,
                model_name=response.model,
                timestamp=datetime.utcnow(),
                metadata=response.metadata or {},
            )
        )

        # Output results
        if fmt == "json":
            out(
                {
                    "prompt_name": execution_name,
                    "output": response.content,
                    "model": response.model,
                    "usage": response.usage,
                },
                fmt,
            )
            return
        click.echo(response.content)

    return CommandManifest(name="apply", click_command=apply_cmd)
