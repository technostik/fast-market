from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from common.core.config import (
    ConfigError,
    load_common_config,
    load_tool_config,
    requires_common_config,
)
from common.llm.registry import discover_providers, get_default_provider_name
from core.router import CLIInteractionPlugin, run_router


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("run")
    @click.argument("task")
    @click.option(
        "--provider",
        "-P",
        default=None,
        help="LLM provider for routing and execution",
    )
    @click.option(
        "--model",
        "-m",
        default=None,
        help="LLM model for routing",
    )
    @click.option(
        "--workdir",
        "-w",
        default=None,
        type=click.Path(),
        help="Working directory (default: common config workdir or current dir)",
    )
    @click.option(
        "--max-iterations",
        "-i",
        type=int,
        default=10,
        help="Max number of skill executions",
    )
    @click.option(
        "--verbose",
        "-v",
        is_flag=True,
        help="Print each skill attempt and distilled result",
    )
    @click.option(
        "--retry-limit",
        type=int,
        default=2,
        help="Max retries per failed skill",
    )
    @click.option(
        "--auto-learn",
        "-L",
        is_flag=True,
        help="After each skill execution, update LEARN.md for that skill",
    )
    @click.option(
        "--compact",
        "-C",
        is_flag=True,
        help="Use compacting prompt to consolidate multiple learnings",
    )
    @click.option(
        "--no-ask",
        is_flag=True,
        default=False,
        help="Disable user interaction — router will not ask questions (treat as failure instead)",
    )
    @click.option(
        "--no-eval",
        is_flag=True,
        default=False,
        help="Skip evaluation phase — don't check if each step satisfies success criteria",
    )
    @click.option(
        "--save-session",
        "-S",
        is_flag=True,
        default=False,
        help="Save each skill's session to {subdir}/{skill_name}.session.yaml",
    )
    def run_cmd(
        task,
        provider,
        model,
        workdir,
        max_iterations,
        verbose,
        retry_limit,
        auto_learn,
        compact,
        no_ask,
        no_eval,
        save_session,
    ):
        """Orchestrate multiple skills to accomplish a complex task.

        The router plans each step using an LLM, then executes skills or
        free-form tasks directly (no subprocess). Results and context are
        passed in-memory between steps.
        """
        if workdir is None:
            common_config = load_common_config()
            workdir = common_config.get("workdir") or "."

        requires_common_config("skill", ["llm"])
        try:
            config = load_tool_config("skill")
            providers = discover_providers(config)
            provider_name = provider or get_default_provider_name(config)
            llm = providers.get(provider_name)
        except ConfigError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

        if not llm:
            click.echo(f"Error: provider '{provider_name}' not available.", err=True)
            sys.exit(1)

        interaction = _NoAskPlugin() if no_ask else CLIInteractionPlugin()

        click.echo(f"Router started: '{task}'", err=True)
        click.echo(f"Provider: {provider_name}, model: {model or 'default'}", err=True)

        state = run_router(
            goal=task,
            provider=llm,
            model=model,
            workdir=workdir,
            max_iterations=max_iterations,
            skill_timeout=300,
            retry_limit=retry_limit,
            verbose=verbose,
            auto_learn=auto_learn,
            compact=compact,
            interaction=interaction,
            skip_evaluation=no_eval,
            save_session=save_session,
        )
        click.echo("\n" + "=" * 50, err=True)
        if state.done:
            click.echo(f"✓ Done: {state.final_result}", err=True)
            return
        if state.failed:
            click.echo(f"✗ Failed: {state.failure_reason}", err=True)
            sys.exit(1)
        click.echo(
            f"✗ Max iterations ({max_iterations}) reached without completion",
            err=True,
        )
        sys.exit(1)

    return CommandManifest(name="run", click_command=run_cmd)


class _NoAskPlugin(CLIInteractionPlugin):
    """Interaction plugin that refuses all questions — for non-interactive use."""

    def ask(self, question: str) -> str:
        # Return empty string; the router will treat this as a non-answer
        # and the planner will have to decide next step with no answer.
        return "(no answer — non-interactive mode)"
