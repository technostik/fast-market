from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from commands.params import RunPlanFileType
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
    @click.option(
        "--export",
        "-e",
        type=click.Path(),
        default=None,
        help="Export planned skills to YAML file (use '-' for stdout)",
    )
    @click.option(
        "--import",
        "import_plan",
        type=RunPlanFileType(),
        default=None,
        help="Import skill execution plan from YAML file instead of auto-planning (searches in workdir)",
    )
    @click.option(
        "--param",
        "-p",
        "params",
        multiple=True,
        type=str,
        help="Plan parameter KEY=VALUE (can be repeated). Substitutes {{key}} in imported plan.",
    )
    @click.option(
        "--run-isolated",
        is_flag=True,
        default=False,
        help="Create an isolated run directory for the entire run",
    )
    @click.option(
        "--skill-isolated",
        is_flag=True,
        default=False,
        help="Create isolated subdirectory for each skill within the run",
    )
    @click.option(
        "--shared-context",
        is_flag=True,
        default=False,
        help="Enable shared context string that skills can read/write to cooperate",
    )
    @click.option(
        "--interactive",
        "-I",
        is_flag=True,
        default=False,
        help="Interactive mode — approve, skip, edit, or replan each step before execution",
    )
    @click.option(
        "--export-successful",
        "-E",
        type=click.Path(),
        default=None,
        help="Export only the successfully executed steps to a YAML plan file",
    )
    @click.option(
        "--auto-skill",
        is_flag=True,
        default=False,
        help="Convert named tasks (with 'name' field) to auto-skills for learning capabilities",
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
        export,
        import_plan,
        run_isolated,
        skill_isolated,
        shared_context,
        interactive,
        export_successful,
        params,
        auto_skill,
    ):
        """Orchestrate multiple skills to accomplish a complex task.

        The router plans each step using an LLM, then executes skills or
        free-form tasks directly (no subprocess). Results and context are
        passed in-memory between steps.

        Isolation modes:
        - Default: skills use the workdir directly (cooperation enabled)
        - --run-isolated: create one isolated dir for the entire run
        - --skill-isolated: create one run dir + subdirectory per skill

        Interactive mode (--interactive):
        - Before each step, you can approve, skip, edit, or replan
        - Use --export-successful to save the steps that worked
        """
        if workdir is None:
            common_config = load_common_config()
            workdir = common_config.get("workdir") or "."

        # Determine isolation mode
        if skill_isolated:
            isolation_mode = "skill"
        elif run_isolated:
            isolation_mode = "run"
        else:
            isolation_mode = "none"

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

        # Convert -p KEY=VALUE pairs to dict for plan parameter substitution
        import_params = {}
        for p in params:
            if "=" in p:
                k, v = p.split("=", 1)
                import_params[k.strip()] = v.strip()
            else:
                click.echo(f"Warning: invalid param format '{p}', expected KEY=VALUE", err=True)

        # Create shared context if enabled
        shared_ctx = None
        if shared_context:
            from common.agent.shared_context import SharedContext
            shared_ctx = SharedContext()

        click.echo(f"Router started: '{task}'", err=True)
        click.echo(f"Provider: {provider_name}, model: {model or 'default'}", err=True)
        click.echo(f"Isolation mode: {isolation_mode}", err=True)
        click.echo(f"Shared context: {'enabled' if shared_ctx else 'disabled'}", err=True)
        click.echo(f"Interactive mode: {'enabled' if interactive else 'disabled'}", err=True)

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
            isolation_mode=isolation_mode,
            shared_context=shared_ctx,
            export_plan_path=export,
            import_plan_path=import_plan,
            import_params=import_params,
            interactive=interactive,
            auto_skill=auto_skill,
            export_successful_path=export_successful,
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
