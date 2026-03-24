from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest
from commands.task.prompts import build_system_prompt
from common.core.config import load_tool_config


def _get_init_task_config():
    from commands.setup import init_task_config

    return init_task_config


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("show-sys-prompt")
    @click.argument("task_description", default="Preview task")
    @click.option(
        "--workdir", "-w", type=click.Path(), default=None, help="Working directory"
    )
    @click.option("--param", "-p", multiple=True, help="Task parameters (key=value)")
    def show_sys_prompt(
        task_description: str, workdir: str | None, param: tuple[str, ...]
    ):
        """Show the generated system prompt for a task.

        This displays the full system prompt that would be sent to the LLM,
        including all configuration from prompt setup task edit.
        Use this to validate your configuration before running a task.
        """
        init_task_config = _get_init_task_config()
        config = load_tool_config("prompt")
        task = init_task_config(config)

        fastmarket_tools = task.get("fastmarket_tools", {})
        system_commands = task.get("system_commands", [])
        workdir_path = Path(workdir) if workdir else Path.cwd()

        task_params = None
        if param:
            task_params = {}
            for p in param:
                if "=" in p:
                    key, value = p.split("=", 1)
                    task_params[key] = value

        system_prompt = build_system_prompt(
            task_description=task_description,
            fastmarket_tools_config=fastmarket_tools,
            system_commands=system_commands,
            workdir=workdir_path,
            task_params=task_params,
        )

        click.echo(system_prompt)

    return CommandManifest(name="show-sys-prompt", click_command=show_sys_prompt)
