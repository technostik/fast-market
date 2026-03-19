from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.task.executor import (
    _DEFAULT_ALLOWED,
    execute_command,
    validate_workdir,
)
from commands.task.loop import TaskConfig, TaskLoop, run_dry_run
from common.core.paths import get_tool_config


def register(plugin_manifests: dict) -> CommandManifest:
    provider_choices = list(plugin_manifests.keys()) if plugin_manifests else []

    @click.command("task")
    @click.argument("task_description")
    @click.option(
        "--from-file",
        type=click.Path(exists=True),
        help="Load task description from file",
    )
    @click.option(
        "--workdir",
        default=".",
        help="Working directory for command execution",
    )
    @click.option(
        "--param",
        "-p",
        multiple=True,
        help="Task parameter (key=value). Can be repeated. @- reads from stdin, @file reads from file.",
    )
    @click.option(
        "--provider",
        type=click.Choice(provider_choices) if provider_choices else str,
        default=None,
        help="LLM provider to use",
    )
    @click.option(
        "--model",
        default=None,
        help="Override default model",
    )
    @click.option(
        "--max-iterations",
        type=int,
        default=None,
        help="Max tool calls before stopping",
    )
    @click.option(
        "--timeout",
        type=int,
        default=None,
        help="Timeout per command (seconds)",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Show commands without executing",
    )
    @click.option(
        "--debug",
        is_flag=True,
        help="Show full LLM dialogs (requests/responses) for debugging",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format",
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
        config_path = get_tool_config("prompt")
        config = _load_config(config_path)
        task_config = _get_task_config(config, max_iterations, timeout)
        workdir_path = _resolve_workdir(workdir)

        if from_file:
            task_description = Path(from_file).read_text(encoding="utf-8").strip()

        task_params = _resolve_params(param, workdir_path)

        if dry_run:
            run_dry_run(task_description, task_config, workdir_path, task_params)
            return

        provider_name = provider or config.get("default_provider", "anthropic")

        def execute_fn(cmd_str: str):
            return execute_command(
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
        )

        try:
            loop.run(task_description, execute_fn, task_params=task_params)
        except Exception as exc:
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
