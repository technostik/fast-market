from __future__ import annotations

import click
import yaml

from commands.base import CommandManifest
from common.core.yaml_utils import dump_yaml
from common.core.config import _resolve_config_path
from common.core.paths import get_tool_config_path, get_agent_config_path
from commands.setup import (
    load_config,
    run_interactive_wizard,
    init_task_config,
)
from commands.setup.providers import create_providers_group
from commands.setup.task_commands import create_task_commands_group
from commands.setup.task import create_task_group
from commands.setup.task_prompts import create_task_prompts_group
from commands.setup.command_docs_prompts import create_command_docs_prompts_group
from commands.setup.task_edit import edit_task_config
from commands.task.prompts import build_command_documentation


def register(plugin_manifests: dict) -> CommandManifest:
    providers = create_providers_group()
    task_commands = create_task_commands_group()
    task = create_task_group()
    task_prompts = create_task_prompts_group()
    command_docs_prompts = create_command_docs_prompts_group()

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

    @setup_cmd.command("reset")
    @click.option(
        "--agent",
        "target",
        flag_value="agent",
        help="Reset the shared agent configuration",
    )
    @click.option(
        "--prompt",
        "target",
        flag_value="prompt",
        default=True,
        help="Reset the prompt LLM providers configuration (default)",
    )
    def reset_cmd(target):
        """Reset configuration to defaults, keeping a backup."""
        import shutil
        from datetime import datetime

        from common.agent.prompts import (
            DEFAULT_AGENT_PROMPT_TEMPLATE,
            DEFAULT_SYSTEM_COMMANDS,
            default_fastmarket_tools_dict,
            DEFAULT_EVALUATION_PROMPT,
            DEFAULT_PLAN_PROMPT,
            DEFAULT_PREPARATION_PROMPT,
        )
        from common.learn import SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE

        if target == "agent":
            config_path = get_agent_config_path()
            click.echo("Resetting agent configuration...")
        else:
            config_path = get_tool_config_path("prompt")
            click.echo("Resetting prompt configuration...")

        if config_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_path = Path(f"{config_path}.{timestamp}.bak")
            shutil.copy2(config_path, backup_path)
            click.echo(f"Backed up to: {backup_path}")

        if target == "agent":
            default_config = {
                "fastmarket_tools": default_fastmarket_tools_dict(),
                "system_commands": list(DEFAULT_SYSTEM_COMMANDS),
                "max_iterations": 20,
                "default_timeout": 60,
                "agent_prompt": {
                    "active": "default",
                    "templates": {
                        "default": {
                            "description": "Default agent execution prompt",
                            "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                        },
                    },
                },
                "command_docs": {
                    "active": "minimal",
                    "templates": {
                        "full": {
                            "description": "Verbose with full documentation",
                            "template": "{aliases}{fastmarket_tools}{system_commands}",
                        },
                        "minimal": {
                            "description": "Brief with descriptions",
                            "template": "{fastmarket_tools_brief}{system_commands_minimal}",
                        },
                    },
                },
                "preparation_prompt": DEFAULT_PREPARATION_PROMPT,
                "evaluation_prompt": DEFAULT_EVALUATION_PROMPT,
                "plan_prompt": DEFAULT_PLAN_PROMPT,
                "skill_from_description_prompt": SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE,
            }
        else:
            default_config = {}

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            dump_yaml(default_config, sort_keys=False),
            encoding="utf-8",
        )
        click.echo(f"Default configuration written to: {config_path}")

    setup_cmd.add_command(providers)
    setup_cmd.add_command(task_commands)
    setup_cmd.add_command(task)
    setup_cmd.add_command(task_prompts)
    setup_cmd.add_command(command_docs_prompts)

    return CommandManifest(name="setup", click_command=setup_cmd)
