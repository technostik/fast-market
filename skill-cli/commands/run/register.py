from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from commands.base import CommandManifest
from common.core.config import (
    ConfigError,
    load_common_config,
    load_tool_config,
    requires_common_config,
    is_workdir_locked,
    add_workdir_lock,
    remove_workdir_lock,
    get_lock_wait_timeout,
    save_common_config,
)
from common.llm.registry import discover_providers, get_default_provider_name
from core.router import (
    CLIInteractionPlugin,
    run_router,
    calculate_run_statistics,
    format_statistics,
    _execution_log_to_yaml,
)


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
        "--param",
        "-p",
        "params",
        multiple=True,
        type=str,
        help="Plan parameter KEY=VALUE (can be repeated). Substitutes {{key}} in plan.",
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
        params,
        run_isolated,
        skill_isolated,
        shared_context,
        interactive,
        export_successful,
    ):
        """Orchestrate multiple skills to accomplish a complex task.

        The router plans each step using an LLM, then executes skills or
        free-form tasks directly (no subprocess). Results and context are
        passed in-memory between steps.

        To execute a plan file instead, use: skill exec <plan.yaml>

        Isolation modes:
        - Default: skills use the workdir directly (cooperation enabled)
        - --run-isolated: create one isolated dir in workdir_root for the entire run
        - --skill-isolated: create one run dir + subdirectory per skill in workdir_root

        Interactive mode (--interactive):
        - Before each step, you can approve, skip, edit, or replan
        - Use --export-successful to save the steps that worked
        """
        created_isolated_workdir = None
        if workdir is None:
            common_config = load_common_config()
            workdir = common_config.get("workdir") or "."

        if (run_isolated or skill_isolated):
            common_config = load_common_config()
            current_workdir = common_config.get("workdir")
            if current_workdir and is_workdir_locked(current_workdir):
                timeout = get_lock_wait_timeout()
                start_time = time.time()
                click.echo(f"Current workdir is locked. Waiting up to {timeout}s for unlock...", err=True)
                while time.time() - start_time < timeout:
                    time.sleep(1)
                    if not is_workdir_locked(current_workdir):
                        click.echo("Current workdir unlocked.", err=True)
                        break
                else:
                    click.echo(f"Error: Timeout waiting for workdir to unlock.", err=True)
                    sys.exit(1)

            import uuid
            workdir_root = common_config.get("workdir_root")
            workdir_prefix = common_config.get("workdir_prefix", "work-")
            if workdir_root:
                root_path = Path(workdir_root).expanduser().resolve()
                root_path.mkdir(parents=True, exist_ok=True)
                short_id = uuid.uuid4().hex[:6]
                dir_name = f"{workdir_prefix}{short_id}"
                new_workdir = root_path / dir_name
                new_workdir.mkdir(parents=True, exist_ok=True)

                created_isolated_workdir = str(new_workdir)
                common_config["previous_workdir"] = common_config.get("workdir")
                common_config["workdir"] = created_isolated_workdir
                save_common_config(common_config)
                add_workdir_lock(created_isolated_workdir)
                click.echo(f"Created and locked isolated workdir: {created_isolated_workdir}", err=True)
                workdir = created_isolated_workdir

                isolation_mode_override = "none"
            else:
                isolation_mode_override = None
        else:
            isolation_mode_override = None

        if workdir is None:
            common_config = load_common_config()
            workdir = common_config.get("workdir") or "."

        # Determine isolation mode
        if isolation_mode_override is not None:
            isolation_mode = isolation_mode_override
        elif skill_isolated:
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
                click.echo(
                    f"Warning: invalid param format '{p}', expected KEY=VALUE", err=True
                )

        # Create shared context if enabled
        shared_ctx = None
        if shared_context:
            from common.agent.shared_context import SharedContext

            shared_ctx = SharedContext()

        click.echo(f"Router started: '{task}'", err=True)
        click.echo(f"Provider: {provider_name}, model: {model or 'default'}", err=True)
        click.echo(f"Isolation mode: {isolation_mode}", err=True)
        if isolation_mode != "none":
            click.echo(f"Workdir: {workdir}", err=True)
        click.echo(
            f"Shared context: {'enabled' if shared_ctx else 'disabled'}", err=True
        )
        click.echo(
            f"Interactive mode: {'enabled' if interactive else 'disabled'}", err=True
        )

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
            import_params=import_params,
            interactive=interactive,
            export_successful_path=export_successful,
        )

        # Display statistics
        stats = calculate_run_statistics(state)
        stats_output = format_statistics(stats)
        click.echo("\n" + stats_output, err=True)

        # Display detailed error report for failed steps
        failed_attempts = [
            a for a in state.attempts if not a.success and a.exit_code != 0
        ]
        if failed_attempts:
            click.echo("\n" + "=" * 60, err=True)
            click.echo("FAILED STEPS ERROR REPORT", err=True)
            click.echo("=" * 60, err=True)
            for attempt in failed_attempts:
                click.echo(
                    f"\nStep {attempt.iteration}: {attempt.skill_name} ({attempt.action})",
                    err=True,
                )
                click.echo(f"Exit code: {attempt.exit_code}", err=True)
                if attempt.params:
                    click.echo(f"Params: {attempt.params}", err=True)
                if attempt.runner_summary:
                    click.echo(f"\nSummary:", err=True)
                    click.echo(attempt.runner_summary.strip(), err=True)
                if attempt.raw_output:
                    click.echo(f"\nRaw output:", err=True)
                    click.echo(attempt.raw_output.strip(), err=True)
                click.echo("-" * 60, err=True)

        # Write full error log to run_dir
        if failed_attempts:
            from pathlib import Path

            # Write to run_root (the actual run directory) if available, otherwise workdir
            if state.run_root is not None:
                log_path = state.run_root / "error_log.yaml"
            else:
                workdir_path = Path(workdir) if isinstance(workdir, str) else workdir
                log_path = workdir_path / "error_log.yaml"
            try:
                log_content = _execution_log_to_yaml(state)
                log_path.write_text(log_content, encoding="utf-8")
                click.echo(f"\n✓ Full error log written to: {log_path}", err=True)
            except Exception as e:
                click.echo(f"\n✗ Failed to write error log: {e}", err=True)

        if state.done:
            click.echo(f"✓ Done: {state.final_result}", err=True)
            if created_isolated_workdir:
                remove_workdir_lock(created_isolated_workdir)
                common_config = load_common_config()
                if common_config.get("previous_workdir"):
                    common_config["workdir"] = common_config.get("previous_workdir")
                    save_common_config(common_config)
                click.echo(f"Released isolated workdir: {created_isolated_workdir}", err=True)
            return
        if state.failed:
            click.echo(f"✗ Failed: {state.failure_reason}", err=True)
            if created_isolated_workdir:
                remove_workdir_lock(created_isolated_workdir)
                common_config = load_common_config()
                if common_config.get("previous_workdir"):
                    common_config["workdir"] = common_config.get("previous_workdir")
                    save_common_config(common_config)
                click.echo(f"Released isolated workdir: {created_isolated_workdir}", err=True)
            sys.exit(1)
        click.echo(
            f"✗ Max iterations ({max_iterations}) reached without completion",
            err=True,
        )
        if created_isolated_workdir:
            remove_workdir_lock(created_isolated_workdir)
            common_config = load_common_config()
            if common_config.get("previous_workdir"):
                common_config["workdir"] = common_config.get("previous_workdir")
                save_common_config(common_config)
            click.echo(f"Released isolated workdir: {created_isolated_workdir}", err=True)
        sys.exit(1)

    return CommandManifest(name="run", click_command=run_cmd)


class _NoAskPlugin(CLIInteractionPlugin):
    """Interaction plugin that refuses all questions — for non-interactive use."""

    def ask(self, question: str) -> str:
        # Return empty string; the router will treat this as a non-answer
        # and the planner will have to decide next step with no answer.
        return "(no answer — non-interactive mode)"
