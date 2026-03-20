from __future__ import annotations

import sys
from pathlib import Path

import click

from common.core.config import _resolve_config_path
from commands.setup import (
    load_config,
    save_config,
    get_tools_doc_prompts_dir,
    run_default_editor,
)
from core.task_prompt import TaskPromptConfig
from commands.task.prompts import DEFAULT_TOOLS_DOC_TEMPLATE


def create_tools_doc_prompts_group() -> click.Group:
    @click.group("tools-doc-prompts")
    def tools_doc_prompts():
        """Manage tools documentation prompt templates."""
        pass

    @tools_doc_prompts.command("list")
    def list_tools_doc_prompts():
        """List available tools doc prompts."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        prompts_dir = get_tools_doc_prompts_dir()
        active = config.get("tools_doc_prompt", "default")

        click.echo("Available tools doc prompts:")

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

    @tools_doc_prompts.command("set")
    @click.argument("name")
    def set_tools_doc_prompt(name: str):
        """Set active tools doc prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        if name == "default":
            config["tools_doc_prompt"] = name
            save_config(config_path, config)
            click.echo(f"✓ Active tools doc prompt set to: default (built-in)")
            return

        prompts_dir = get_tools_doc_prompts_dir()
        prompt_file = prompts_dir / f"{name}.yaml"
        if not prompt_file.exists():
            click.echo(f"Error: Tools doc prompt '{name}' not found", err=True)
            sys.exit(1)

        config["tools_doc_prompt"] = name
        save_config(config_path, config)
        click.echo(f"✓ Active tools doc prompt set to: {name}")

    @tools_doc_prompts.command("show")
    @click.argument("name")
    def show_tools_doc_prompt(name: str):
        """Show a tools doc prompt's configuration."""
        if name == "default":
            click.echo(f"=== Default Tools Doc Prompt ===")
            click.echo(f"Name: default")
            click.echo(f"Description: Default tools documentation")
            click.echo(f"\nTemplate:\n")
            click.echo(DEFAULT_TOOLS_DOC_TEMPLATE)
            return

        prompts_dir = get_tools_doc_prompts_dir()
        prompt_file = prompts_dir / f"{name}.yaml"
        if not prompt_file.exists():
            click.echo(f"Error: Tools doc prompt '{name}' not found", err=True)
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

    @tools_doc_prompts.command("edit")
    @click.argument("name")
    def edit_tools_doc_prompt(name: str):
        """Edit a tools doc prompt in the default editor."""
        prompts_dir = get_tools_doc_prompts_dir()

        if name == "default":
            click.echo("Error: Cannot edit the built-in default prompt", err=True)
            sys.exit(1)

        prompt_file = prompts_dir / f"{name}.yaml"
        if not prompt_file.exists():
            click.echo(f"Prompt '{name}' not found. Creating new prompt...")
            default_config = TaskPromptConfig(
                name=name,
                description="Custom tools doc prompt",
                template=DEFAULT_TOOLS_DOC_TEMPLATE,
            )
            default_config.save(prompt_file)
            click.echo(f"Created: {prompt_file}")

        run_default_editor(prompt_file)
        click.echo(f"✓ Edited tools doc prompt: {name}")

    @tools_doc_prompts.command("import")
    @click.argument("file", type=click.Path(exists=True))
    def import_tools_doc_prompt(file: str):
        """Import a tools doc prompt from a YAML file."""
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

        prompts_dir = get_tools_doc_prompts_dir()
        target_file = prompts_dir / f"{prompt_config.name}.yaml"

        if target_file.exists():
            if not click.confirm(
                f"Tools doc prompt '{prompt_config.name}' exists. Overwrite?"
            ):
                click.echo("Import cancelled.")
                return

        prompt_config.save(target_file)
        click.echo(
            f"✓ Imported tools doc prompt '{prompt_config.name}' to: {target_file}"
        )

    return tools_doc_prompts
