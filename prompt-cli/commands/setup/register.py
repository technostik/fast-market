from __future__ import annotations

import click
import yaml

from commands.base import CommandManifest
from common.core.yaml_utils import dump_yaml
from common.core.config import _resolve_config_path
from commands.setup import (
    load_config,
    run_interactive_wizard,
    init_task_config,
)
from commands.setup.providers import create_providers_group
from commands.setup.task_commands import create_task_commands_group
from commands.setup.task import create_task_group
from commands.setup.task_prompts import create_task_prompts_group
from commands.setup.tools_doc_prompts import create_tools_doc_prompts_group
from commands.setup.task_edit import edit_task_config
from commands.task.prompts import build_command_documentation


def register(plugin_manifests: dict) -> CommandManifest:
    providers = create_providers_group()
    task_commands = create_task_commands_group()
    task = create_task_group()
    task_prompts = create_task_prompts_group()
    tools_doc_prompts = create_tools_doc_prompts_group()

    @click.group("setup", invoke_without_command=True)
    @click.option(
        "--show-config", "-c", is_flag=True, help="Show current configuration"
    )
    @click.option("--config-path", "-p", is_flag=True, help="Show config file path")
    @click.option(
        "--show-task-tools",
        "-t",
        is_flag=True,
        help="Show the inner tool documentation",
    )
    @click.pass_context
    def setup_cmd(ctx, show_config, config_path, show_task_tools):
        ctx.ensure_object(dict)

        if ctx.invoked_subcommand is not None:
            return

        config_path_val = _resolve_config_path("prompt")
        config = load_config(config_path_val)
        ctx.obj["config"] = config
        ctx.obj["config_path"] = config_path_val

        if show_config:
            click.echo(dump_yaml(config, sort_keys=False))
            return

        if config_path:
            click.echo(config_path_val)
            return

        if show_task_tools:
            task = init_task_config(config)
            allowed_commands = task.get("allowed_commands", [])
            docs = build_command_documentation(allowed_commands)
            click.echo(docs)
            return

        run_interactive_wizard(config_path_val, config)

    @setup_cmd.command("edit")
    def edit_cmd():
        """Edit the full configuration file in the default editor."""
        edit_task_config()

    setup_cmd.add_command(providers)
    setup_cmd.add_command(task_commands)
    setup_cmd.add_command(task)
    setup_cmd.add_command(task_prompts)
    setup_cmd.add_command(tools_doc_prompts)

    return CommandManifest(name="setup", click_command=setup_cmd)
