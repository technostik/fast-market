from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.task.executor import (
    resolve_and_execute_command,
    validate_workdir,
)
from commands.task.loop import TaskConfig, TaskLoop, run_dry_run
from common.core.config import load_tool_config, get_tool_config_path, ConfigError
from common.llm.registry import get_default_provider_name


def _default_fastmarket_tools():
    return {
        "corpus": "Search and retrieve indexed documents",
        "image": "Generate images from text prompts",
        "youtube": "Access YouTube tools",
        "message": "Send messages",
        "prompt": "Apply prompt templates",
        "task": "Execute agentic task",
        "skill": "Execute skill scripts",
    }


def _default_system_commands():
    return {
        "ls": "List directory contents (ls [-la] [path])",
        "cat": "Display file contents (cat [file])",
        "grep": "Search file contents (grep pattern [file])",
        "find": "Find files (find [path] -name [pattern])",
        "echo": "Print text (echo [text])",
        "head": "Display first lines (head -n [n] [file])",
        "tail": "Display last lines (tail -n [n] [file])",
        "wc": "Count lines/words (wc [-lwc] [file])",
        "mkdir": "Create directory (mkdir [path])",
        "touch": "Create empty file (touch [file])",
        "rm": "Remove file (rm [-rf] [path])",
        "cp": "Copy file (cp [src] [dst])",
        "mv": "Move file (mv [src] [dst])",
        "sort": "Sort file contents (sort [file])",
        "uniq": "Remove duplicates (uniq [file])",
        "awk": "Process text (awk 'pattern' [file])",
        "sed": "Text substitution (sed 's/old/new/' [file])",
        "jq": "JSON processor (jq '.key' [file])",
    }


def register(plugin_manifests: dict) -> CommandManifest:
    provider_choices = list(plugin_manifests.keys()) if plugin_manifests else []

    @click.command(name="apply")
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
    def apply_cmd(
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
        """
        if debug and debug not in ("normal", "full"):
            raise click.BadParameter("--debug must be 'normal' or 'full'")

        common_config = load_tool_config("apply")
        from commands.setup import init_task_config, load_task_config

        task_file_config = load_task_config()
        task_config_dict = init_task_config(task_file_config)

        fastmarket_tools = task_config_dict.get("fastmarket_tools", {})
        system_commands = task_config_dict.get("system_commands", [])
        allowed_commands = list(fastmarket_tools.keys()) + system_commands
        task_config = TaskConfig(
            fastmarket_tools=fastmarket_tools,
            system_commands=system_commands,
            allowed_commands=allowed_commands,
            max_iterations=max_iterations or task_config_dict.get("max_iterations", 20),
            default_timeout=timeout or task_config_dict.get("default_timeout", 60),
        )

        resolved_workdir = (
            workdir
            or common_config.get("workdir")
            or task_config_dict.get("default_workdir")
            or "."
        )
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

        try:
            provider_name = provider or get_default_provider_name(config)
        except ConfigError:
            click.echo("Error: No default LLM provider configured.", err=True)
            click.echo("Run: common-setup", err=True)
            sys.exit(1)

        if not provider_name:
            click.echo("Error: No LLM provider available.", err=True)
            sys.exit(1)

        provider_instance = plugin_manifests.get(provider_name)
        if not provider_instance:
            click.echo(f"Error: Provider '{provider_name}' not available.", err=True)
            sys.exit(1)

        if dry_run:
            click.echo(f"Task: {task_description}")
            click.echo(f"Workdir: {workdir_path}")
            task_config.max_iterations = 1
            run_dry_run(
                task_description,
                task_config,
                workdir_path,
                task_params=task_params,
            )
            return

        loop = TaskLoop(
            config=task_config,
            workdir=workdir_path,
            provider=provider_name,
            model=model,
            verbose=ctx.obj.get("verbose", False),
            debug=debug,
            silent=silent,
        )

        from functools import partial

        execute_fn = partial(
            resolve_and_execute_command,
            workdir=workdir_path,
            allowed=set(task_config.allowed_commands),
            timeout=task_config.default_timeout,
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

    return CommandManifest(name="apply", click_command=apply_cmd)


def _resolve_workdir(path: str) -> Path:
    path = Path(path).expanduser().resolve()
    forbidden = [
        Path("/"),
        Path("/bin"),
        Path("/sbin"),
        Path("/usr"),
        Path("/lib"),
        Path("/lib64"),
        Path("/etc"),
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
