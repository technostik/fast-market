from __future__ import annotations

import sys
from pathlib import Path

import click

_ROOT = Path(__file__).resolve().parents[1]
_COMMON_PARENT = _ROOT.parent
for p in [str(_ROOT), str(_COMMON_PARENT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.core.config import load_tool_config, ConfigError, requires_common_config
from common.llm.registry import discover_providers
from common.cli.base import create_cli_group

requires_common_config("apply", ["llm"])

TASK_DEFAULT_PROMPTS = {
    "agent": """You are a task execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

# Your Task
{task_description}
{params_section}

# Working Directory
All commands execute in: `{workdir}`

You can read and write files in this directory. Relative paths are resolved from here.

---

{command_docs}

---

# How to Work

1. **Understand the task**: Break it down into clear steps
2. **Explore first**: Use `ls` and `cat` to understand what files exist
3. **Execute incrementally**: Run one command, check the result, then decide next step
4. **Handle errors**: If a command fails, read the error message and try a different approach
5. **Stay focused**: Only use commands that advance the task
6. **Finish clearly**: When done, summarize what you accomplished (without making tool calls)

# Critical Rules

- **Only use listed commands** - others will be rejected
- **Work within the directory** - you cannot escape `{workdir}`
- **Check outputs** - always verify command results before proceeding
- **Be efficient** - prefer one good command over many guesses
- **Ask for help** - if truly stuck, explain what you need
""",
}


def _load():
    try:
        config = load_tool_config("apply")
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        plugin_manifests = discover_providers(config)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        click.echo("Run: common-setup", err=True)
        sys.exit(1)

    from commands.task.register import register as task_register, report_cmd
    from commands.setup.register import register as setup_register
    from common.prompt import register_commands, get_prompt_manager

    main = create_cli_group("apply", default_command="apply")
    main.add_command(task_register(plugin_manifests).click_command)
    main.add_command(report_cmd)
    main.add_command(setup_register())

    _prompt_manager = get_prompt_manager("task", TASK_DEFAULT_PROMPTS)
    register_commands(main, "task", TASK_DEFAULT_PROMPTS)

    return main


main = _load()

__all__ = ["main"]
