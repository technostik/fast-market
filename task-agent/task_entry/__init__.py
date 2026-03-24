from __future__ import annotations

import sys
from pathlib import Path

import click

_ROOT = Path(__file__).resolve().parents[1]
_COMMON_PARENT = _ROOT.parent
for p in [str(_ROOT), str(_COMMON_PARENT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.core.config import load_tool_config, ConfigError
from common.llm.registry import discover_providers
from common.cli.base import create_cli_group


def _load():
    try:
        config = load_tool_config("task")
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        plugin_manifests = discover_providers(config)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        click.echo("Run: global-setup", err=True)
        sys.exit(1)

    from commands.task.register import register as task_register
    from commands.setup.register import register as setup_register

    main = create_cli_group("task", default_command="task")
    main.add_command(task_register(plugin_manifests).click_command)
    main.add_command(setup_register())

    return main


main = _load()

__all__ = ["main"]
