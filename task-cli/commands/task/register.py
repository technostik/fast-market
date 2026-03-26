from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.completion import ProviderParamType
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
        type=ProviderParamType(),
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
        "--auto-learn",
        "-L",
        is_flag=True,
        help="After task completion, analyze session and update LEARN.md for the skill",
    )
    @click.option(
        "--learn-skill",
        default=None,
        help="Skill name to write LEARN.md to (required if --auto-learn and task is not 'skill apply ...')",
    )
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
        auto_learn,
        learn_skill,
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
            provider_name = provider or get_default_provider_name(common_config)
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

        if learn_skill and not auto_learn:
            click.echo(
                "[AUTO-LEARN] Warning: --learn-skill has no effect without --auto-learn.",
                err=True,
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

        from functools import partial

        execute_fn = partial(
            resolve_and_execute_command,
            workdir=workdir_path,
            allowed=set(task_config.allowed_commands),
            timeout=task_config.default_timeout,
        )

        try:
            loop.run(task_description, execute_fn, task_params=task_params)

            if auto_learn and loop.session:
                inferred_skill = learn_skill or _infer_skill_name(
                    task_description,
                    session=loop.session,
                )
                if not inferred_skill and not silent:
                    click.echo(
                        "[AUTO-LEARN] Warning: could not infer skill name from task/session for skill apply/run.",
                        err=True,
                    )
                    click.echo(
                        "[AUTO-LEARN] Use --learn-skill <name> to specify the skill.",
                        err=True,
                    )
                _run_auto_learn(
                    session=loop.session,
                    skill_name=inferred_skill,
                    provider_instance=provider_instance,
                    model=model,
                    config=task_config_dict,
                    silent=silent,
                )

            if save_session and loop.session:
                session_path = Path(save_session)
                loop.session.end_time = datetime.utcnow()
                loop.session.save(session_path)
                if not silent:
                    click.echo(f"\nSession saved to: {session_path}")

            if not silent and loop.session:
                m = loop.session.metrics_dict()
                click.echo(
                    "\n── Session Metrics ──────────────────────────\n"
                    f"  Tool calls : {m['total_tool_calls']}\n"
                    f"  Rounds     : {m['iterations_used']}\n"
                    f"  Errors     : {m['error_count']}\n"
                    f"  Guesses    : {m['guess_count']}\n"
                    f"  Success    : {m['success_rate']:.0%}\n"
                    "────────────────────────────────────────────",
                    err=True,
                )

            if debug == "full" and not silent and loop.session:
                click.echo("\n" + "=" * 60, file=sys.stderr)
                click.echo("FULL SESSION YAML:", file=sys.stderr)
                click.echo(loop.session.to_yaml(), file=sys.stderr)

        except Exception as exc:
            if loop.session:
                loop.session.exit_code = 1
                loop.session.error = str(exc)
                loop.session.end_reason = f"internal failure: {exc}"
                if save_session:
                    loop.session.save(Path(save_session))
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

    return CommandManifest(name="apply", click_command=apply_cmd)


@click.command("report")
@click.argument("session_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "-F",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
)
def report_cmd(session_file, fmt):
    """Show metrics and error summary for a saved session."""
    data = yaml.safe_load(Path(session_file).read_text(encoding="utf-8")) or {}

    metrics = data.get("metrics", {})
    turns = data.get("turns", [])

    failures = []
    for turn in turns:
        for tc in turn.get("tool_calls", []):
            exit_code = tc.get("exit_code")
            if exit_code is not None and exit_code != 0:
                failures.append(
                    {
                        "command": tc.get("arguments", {}).get("command", ""),
                        "exit_code": exit_code,
                        "stderr": tc.get("stderr", "")[:200],
                        "stdout": tc.get("stdout", "")[:200],
                    }
                )

    if fmt == "json":
        click.echo(json.dumps({"metrics": metrics, "failures": failures}, indent=2))
        return

    click.echo(f"\nSession: {session_file}")
    click.echo(f"Task: {str(data.get('task_description', ''))[:80]}")
    click.echo("\n── Metrics ──────────────────")
    for k, v in metrics.items():
        click.echo(f"  {k}: {v}")

    if failures:
        click.echo(f"\n── Failures ({len(failures)}) ──────────────")
        for i, failure in enumerate(failures, 1):
            click.echo(f"  [{i}] cmd: {failure['command']}")
            click.echo(f"      exit: {failure['exit_code']}")
            if failure["stderr"]:
                click.echo(f"      err: {failure['stderr'][:100]}")
    else:
        click.echo("\n  No failures ✓")


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


def _infer_skill_name(task_description: str, session=None) -> str | None:
    """Try to extract skill name from skill apply/run tasks and session tool calls."""
    import re

    desc = task_description.strip()
    m = re.match(r"skill\s+apply\s+([a-zA-Z0-9_-]+)", desc)
    if m:
        return m.group(1)

    if re.match(r"skill\s+run\b", desc) and session:
        return _infer_skill_name_from_session(session)

    return None


def _infer_skill_name_from_session(session) -> str | None:
    """Infer skill name by scanning executed commands and routing output."""
    import re

    for turn in reversed(session.turns):
        for tc in reversed(turn.tool_calls):
            command = (tc.arguments or {}).get("command", "").strip()

            m = re.match(r"skill:([a-zA-Z0-9_-]+)", command)
            if m:
                return m.group(1)

            m = re.match(r"skill\s+apply\s+([a-zA-Z0-9_-]+)", command)
            if m:
                return m.group(1)

            route_text = f"{tc.stdout or ''}\n{tc.stderr or ''}"
            m = re.search(r"Matched:\s+'([a-zA-Z0-9_-]+)'", route_text)
            if m:
                return m.group(1)

    return None


def _run_auto_learn(session, skill_name, provider_instance, model, config, silent):
    if not skill_name:
        if not silent:
            click.echo("[AUTO-LEARN] Skipped: no skill name", err=True)
        return

    from commands.task.learner import analyze_session, update_learn_file

    if not silent:
        click.echo(
            f"\n[AUTO-LEARN] Analyzing session for skill '{skill_name}'...",
            err=True,
        )

    try:
        learn_prompt = config.get("learn_prompt", None)
        content = analyze_session(
            session,
            skill_name,
            provider_instance,
            model,
            learn_prompt,
        )
        path = update_learn_file(
            skill_name,
            content,
            provider=provider_instance,
            model=model,
        )
        if not silent:
            click.echo(f"[AUTO-LEARN] LEARN.md updated: {path}", err=True)
    except Exception as exc:
        click.echo(f"[AUTO-LEARN] Failed: {exc}", err=True)
