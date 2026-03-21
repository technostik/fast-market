from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.task.executor import (
    _DEFAULT_ALLOWED,
    resolve_and_execute_command,
    validate_workdir,
)
from commands.task.loop import TaskConfig, TaskLoop, run_dry_run
from common.core.config import _resolve_config_path


def register(plugin_manifests: dict) -> CommandManifest:
    provider_choices = list(plugin_manifests.keys()) if plugin_manifests else []

    @click.command("task")
    @click.argument("task_description")
    @click.option(
        "--from-file",
        "-f",
        type=click.Path(exists=True),
        help="Load task description from file",
    )
    @click.option(
        "--workdir",
        "-w",
        default=None,
        help="Working directory for command execution (default: from config or cwd)",
    )
    @click.option(
        "--param",
        "-p",
        multiple=True,
        help="Task parameter (key=value). Can be repeated.",
    )
    @click.option(
        "--provider",
        "-P",
        type=click.Choice(provider_choices) if provider_choices else str,
        default=None,
        help="LLM provider to use",
    )
    @click.option("--model", "-m", default=None, help="Override default model")
    @click.option(
        "--max-iterations",
        "-i",
        type=int,
        default=None,
        help="Max tool calls before stopping",
    )
    @click.option(
        "--timeout", "-t", type=int, default=None, help="Timeout per command (seconds)"
    )
    @click.option(
        "--dry-run", "-n", is_flag=True, help="Show commands without executing"
    )
    @click.option(
        "--debug", "-d", type=str, default="", help="Debug output: 'normal' or 'full'"
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format",
    )
    @click.option("--silent", "-s", is_flag=True, help="Suppress session output")
    @click.option(
        "--save-session",
        "-o",
        type=click.Path(),
        default=None,
        help="Save session to YAML file (relative path uses workdir, default: workdir/.last-session.yaml)",
    )
    @click.pass_context
    def task_cmd(
        ctx,
        task_description,
        from_file,
        workdir,
        param,
        provider,
        model,
        max_iterations,
        timeout,
        dry_run,
        debug,
        fmt,
        silent,
        save_session,
    ):
        """Execute a task with LLM-driven CLI command loop.

        TASK_DESCRIPTION is the task to accomplish.

        Parameters can be passed with --param key=value. Values starting with @ are
        resolved: @- reads from stdin, @filename reads from the file.

        Examples:
          prompt task "analyze {topic}" --param topic="AI trends"
          echo "search query" | prompt task "search corpus" --param query=@-
          prompt task "summarize file" --param input=@data.txt output=summary.txt
        """
        if debug and debug not in ("normal", "full"):
            raise click.BadParameter("--debug must be 'normal' or 'full'")

        config_path = _resolve_config_path("prompt")
        config = _load_config(config_path)
        task_config = _get_task_config(config, max_iterations, timeout)
        resolved_workdir = workdir or config.get("task", {}).get("default_workdir", ".")
        workdir_path = _resolve_workdir(resolved_workdir)
        if save_session is not None:
            save_path = Path(save_session)
            if save_path.is_absolute():
                save_session = str(save_path)
            else:
                save_session = str(workdir_path / save_path)
        else:
            save_session = str(workdir_path / ".last-session.yaml")

        if from_file:
            task_description = Path(from_file).read_text(encoding="utf-8").strip()

        task_params = _resolve_params(param, workdir_path)

        if dry_run:
            run_dry_run(task_description, task_config, workdir_path, task_params)
            return

        provider_name = provider or config.get("default_provider", "anthropic")

        def execute_fn(cmd_str: str):
            return resolve_and_execute_command(
                cmd_str,
                workdir_path,
                task_config.allowed_commands,
                task_config.default_timeout,
            )

        loop = TaskLoop(
            config=task_config,
            workdir=workdir_path,
            provider=provider_name,
            model=model,
            verbose=ctx.obj.get("verbose", False),
            debug=debug,
            silent=silent,
        )

        try:
            loop.run(task_description, execute_fn, task_params=task_params)

            if save_session and loop.session:
                session_path = Path(save_session)
                loop.session.end_time = datetime.utcnow()
                loop.session.save(session_path)
                if not silent:
                    click.echo(f"\nSession saved to: {session_path}")

            if debug == "full" and not silent and loop.session:
                click.echo("\n" + "=" * 60, file=sys.stderr)
                click.echo("FULL SESSION YAML:", file=sys.stderr)
                click.echo(loop.session.to_yaml(), file=sys.stderr)

        except Exception as exc:
            if loop.session:
                loop.session.exit_code = 1
                loop.session.error = str(exc)
                if save_session:
                    loop.session.save(Path(save_session))
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

    return CommandManifest(name="task", click_command=task_cmd)


def _load_config(config_path: Path) -> dict:
    if config_path.exists():
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {}


def _get_task_config(
    config: dict,
    max_iterations: int | None,
    timeout: int | None,
) -> TaskConfig:
    task_section = config.get("task", {})
    allowed = set(task_section.get("allowed_commands", _DEFAULT_ALLOWED))
    return TaskConfig(
        allowed_commands=allowed,
        max_iterations=max_iterations or task_section.get("max_iterations", 20),
        default_timeout=timeout or task_section.get("default_timeout", 60),
    )


def _resolve_workdir(workdir: str) -> Path:
    path = Path(workdir).expanduser().resolve()
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    forbidden = [
        Path("/"),
        Path("/bin"),
        Path("/sbin"),
        Path("/usr"),
        Path("/etc"),
        Path("/boot"),
        Path("/srv"),
        Path("/var"),
        Path("/opt"),
        Path("/sys"),
        Path("/proc"),
        Path("/dev"),
    ]
    validate_workdir(path, forbidden)
    return path


def _resolve_params(params: tuple[str, ...], workdir: Path) -> dict[str, str]:
    """Resolve task parameters from --param arguments.

    Values can be:
    - Literal string: key=value
    - Stdin: key=@- (reads from stdin)
    - File: key=@filename (reads from file)
    """
    result = {}
    for p in params:
        if "=" not in p:
            raise ValueError(f"Invalid parameter format: {p} (expected key=value)")
        key, value = p.split("=", 1)

        if value == "@-":
            if sys.stdin.isatty():
                raise ValueError(
                    f"Parameter '{key}' requires stdin input but none available"
                )
            result[key] = sys.stdin.read().strip()
        elif value.startswith("@"):
            filepath = workdir / value[1:]
            if not filepath.exists():
                raise ValueError(f"Parameter '{key}': file not found: {filepath}")
            result[key] = filepath.read_text(encoding="utf-8").strip()
        else:
            result[key] = value

    return result
