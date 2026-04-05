from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import click
import yaml

from common.core.config import _resolve_config_path
from common.core.yaml_utils import dump_yaml
from commands.setup import (
    load_config,
    save_config,
    init_task_config,
)
from common.agent.prompts import DEFAULT_AGENT_PROMPT_TEMPLATE
from common.cli.helpers import get_editor


def create_task_prompts_group() -> click.Group:
    @click.group("task-prompts")
    def task_prompts():
        """Manage task prompt templates.

        Note: For human-friendly editing, use 'prompt setup task edit'
        to edit all task configuration in one place.
        """
        pass

    @task_prompts.command("list")
    def list_task_prompts():
        """List available task prompts."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        agent_prompt = task.get("agent_prompt", {})
        active = agent_prompt.get("active", "default")
        templates = agent_prompt.get("templates", {})

        click.echo("Available task prompts:")

        marker = "*" if active == "default" else " "
        click.echo(f" {marker} default (built-in) - Default task execution prompt")

        for name, tpl in sorted(templates.items()):
            if name == "default":
                continue
            marker = "*" if active == name else " "
            desc = tpl.get("description", "")
            desc_str = f" - {desc}" if desc else ""
            click.echo(f" {marker} {name}{desc_str}")

    @task_prompts.command("set")
    @click.argument("name")
    def set_task_prompt(name: str):
        """Set active task prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        agent_prompt = task.get("agent_prompt", {})
        templates = agent_prompt.get("templates", {})

        if name not in templates:
            click.echo(f"Error: Task prompt '{name}' not found", err=True)
            click.echo("Available prompts:", err=True)
            for tname in templates.keys():
                click.echo(f"  - {tname}", err=True)
            sys.exit(1)

        agent_prompt["active"] = name
        save_config(config_path, config)
        click.echo(f"✓ Active task prompt set to: {name}")

    @task_prompts.command("show")
    @click.argument("name")
    def show_task_prompt(name: str):
        """Show a task prompt's configuration."""
        if name == "default":
            click.echo(f"=== default (built-in) ===")
            click.echo(f"Description: Default task execution prompt")
            click.echo(f"\nTemplate:\n")
            click.echo(DEFAULT_AGENT_PROMPT_TEMPLATE)
            return

        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        agent_prompt = task.get("agent_prompt", {})
        templates = agent_prompt.get("templates", {})

        if name not in templates:
            click.echo(f"Error: Task prompt '{name}' not found", err=True)
            sys.exit(1)

        tpl = templates[name]
        click.echo(f"=== {name} ===")
        if tpl.get("description"):
            click.echo(f"Description: {tpl['description']}")
        click.echo(f"\nTemplate:\n")
        click.echo(tpl.get("template", ""))

    @task_prompts.command("add")
    @click.argument("name")
    def add_task_prompt(name: str):
        """Add a new task prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        agent_prompt = task.setdefault("agent_prompt", {})
        templates = agent_prompt.setdefault("templates", {})

        if name in templates:
            click.echo(f"Error: Task prompt '{name}' already exists", err=True)
            sys.exit(1)

        templates[name] = {
            "description": f"Custom task prompt: {name}",
            "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
        }
        save_config(config_path, config)
        click.echo(f"✓ Added task prompt: {name}")

        import subprocess

        editor = get_editor()

        yaml_content = dump_yaml(templates[name])
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            prefix=f"fastmarket-task-prompt-{name}-",
            delete=False,
        ) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            subprocess.run([editor, str(temp_path)], check=True)
            new_content = yaml.safe_load(temp_path.read_text())
            if new_content:
                templates[name] = new_content
                save_config(config_path, config)
                click.echo(f"✓ Updated task prompt: {name}")
        finally:
            temp_path.unlink(missing_ok=True)

    return task_prompts
