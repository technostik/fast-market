from __future__ import annotations

import sys
from pathlib import Path

import click

_ROOT = Path(__file__).resolve().parents[1]
_COMMON_PARENT = _ROOT.parent
for p in [str(_ROOT), str(_COMMON_PARENT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.agent.prompts import DEFAULT_AGENT_PROMPT_TEMPLATE
from common.core.config import load_tool_config, ConfigError, requires_common_config
from common.llm.registry import discover_providers
from common.cli.base import create_cli_group

requires_common_config("apply", ["llm"])

TASK_DEFAULT_PROMPTS = {
    "agent": DEFAULT_AGENT_PROMPT_TEMPLATE,
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
        click.echo("Run: toolsetup", err=True)
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
