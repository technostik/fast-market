from __future__ import annotations

import sys
from pathlib import Path

import click

from common.core.config import _resolve_config_path
from commands.setup import (
    load_config,
    save_config,
    get_task_prompts_dir,
    run_default_editor,
)
from core.task_prompt import TaskPromptConfig, DEFAULT_PROMPT_TEMPLATE


def create_task_prompts_group() -> click.Group:
    @click.group("task-prompts")
    def task_prompts():
        """Manage task prompt templates."""
        pass

    @task_prompts.command("list")
    def list_task_prompts():
        """List available task prompts."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        prompts_dir = get_task_prompts_dir()
        active = config.get("task", {}).get("active_prompt", "default")

        click.echo("Available task prompts:")

        marker = "*" if active == "default" else " "
        click.echo(f" {marker} default (built-in)")

        for file in prompts_dir.glob("*.yaml"):
            prompt_config = TaskPromptConfig.from_yaml(file)
            if prompt_config:
                marker = "*" if active == prompt_config.name else " "
                desc = (
                    f" - {prompt_config.description}"
                    if prompt_config.description
                    else ""
                )
                click.echo(f" {marker} {prompt_config.name}{desc}")

    @task_prompts.command("set")
    @click.argument("name")
    def set_task_prompt(name: str):
        """Set active task prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        if name == "default":
            config.setdefault("task", {})["active_prompt"] = name
            save_config(config_path, config)
            click.echo(f"✓ Active task prompt set to: default (built-in)")
            return

        prompts_dir = get_task_prompts_dir()
        prompt_file = prompts_dir / f"{name}.yaml"
        if not prompt_file.exists():
            click.echo(f"Error: Prompt '{name}' not found", err=True)
            sys.exit(1)

        config.setdefault("task", {})["active_prompt"] = name
        save_config(config_path, config)
        click.echo(f"✓ Active task prompt set to: {name}")

    @task_prompts.command("show")
    @click.argument("name")
    def show_task_prompt(name: str):
        """Show a task prompt's configuration."""
        if name == "default":
            click.echo(f"=== Default Task Prompt ===")
            click.echo(f"Name: default")
            click.echo(f"Description: Built-in default task prompt")
            click.echo(f"\nTemplate:\n")
            click.echo(DEFAULT_PROMPT_TEMPLATE)
            return

        prompts_dir = get_task_prompts_dir()
        prompt_file = prompts_dir / f"{name}.yaml"
        if not prompt_file.exists():
            click.echo(f"Error: Task prompt '{name}' not found", err=True)
            sys.exit(1)

        prompt_config = TaskPromptConfig.from_yaml(prompt_file)
        if not prompt_config:
            click.echo(f"Error: Could not parse prompt file", err=True)
            sys.exit(1)

        click.echo(f"=== {prompt_config.name} ===")
        if prompt_config.description:
            click.echo(f"Description: {prompt_config.description}")
        click.echo(f"\nTemplate:\n")
        click.echo(prompt_config.template)

    @task_prompts.command("edit")
    @click.argument("name")
    def edit_task_prompt(name: str):
        """Edit a task prompt in the default editor."""
        prompts_dir = get_task_prompts_dir()

        if name == "default":
            click.echo("Error: Cannot edit the built-in default prompt", err=True)
            sys.exit(1)

        prompt_file = prompts_dir / f"{name}.yaml"
        if not prompt_file.exists():
            click.echo(f"Prompt '{name}' not found. Creating new prompt...")
            default_config = TaskPromptConfig(
                name=name,
                description="Custom task prompt",
                template=DEFAULT_PROMPT_TEMPLATE,
            )
            default_config.save(prompt_file)
            click.echo(f"Created: {prompt_file}")

        run_default_editor(prompt_file)
        click.echo(f"✓ Edited prompt: {name}")

    @task_prompts.command("import")
    @click.argument("file", type=click.Path(exists=True))
    def import_task_prompt(file: str):
        """Import a task prompt from a YAML file."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        source_path = Path(file)
        prompt_config = TaskPromptConfig.from_yaml(source_path)

        if not prompt_config:
            click.echo(f"Error: Could not parse prompt file: {file}", err=True)
            sys.exit(1)

        errors = prompt_config.validate()
        if errors:
            click.echo(f"Error: Invalid prompt configuration:", err=True)
            for err in errors:
                click.echo(f"  - {err}", err=True)
            sys.exit(1)

        prompts_dir = get_task_prompts_dir()
        target_file = prompts_dir / f"{prompt_config.name}.yaml"

        if target_file.exists():
            if not click.confirm(f"Prompt '{prompt_config.name}' exists. Overwrite?"):
                click.echo("Import cancelled.")
                return

        prompt_config.save(target_file)
        click.echo(f"✓ Imported prompt '{prompt_config.name}' to: {target_file}")

    return task_prompts
