from __future__ import annotations

import subprocess
from pathlib import Path

import click
import yaml

from common.core.config import _resolve_config_path
from core.task_prompt import TaskPromptConfig, DEFAULT_PROMPT_TEMPLATE
from commands.task.prompts import (
    build_command_documentation,
    DEFAULT_TOOLS_DOC_TEMPLATE,
)

_SUPPORTED_PROVIDERS = {"anthropic", "openai", "openai-compatible", "ollama"}
_DEFAULT_TASK_COMMANDS = {
    "corpus",
    "image",
    "youtube",
    "message",
    "prompt",
    "ls",
    "cat",
    "jq",
    "grep",
    "find",
    "echo",
    "head",
    "tail",
    "wc",
    "mkdir",
    "touch",
    "rm",
    "cp",
    "mv",
    "sort",
    "uniq",
    "awk",
    "sed",
}


def load_config(config_path: Path) -> dict:
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        config = {}
    if not isinstance(config, dict):
        raise ValueError(f"{config_path.name} must be a mapping")
    providers = config.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("providers must be a mapping")
    return config


def save_config(config_path: Path, config: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def provider_defaults(provider_name: str) -> tuple[str, str, str | None]:
    if provider_name == "anthropic":
        return "claude-sonnet-4-20250514", "ANTHROPIC_API_KEY", None
    if provider_name == "openai":
        return "gpt-4", "OPENAI_API_KEY", None
    if provider_name == "openai-compatible":
        return "gpt-4o-mini", "OPENAI_COMPATIBLE_API_KEY", "https://api.openai.com/v1"
    if provider_name == "ollama":
        return "llama3.2", "", "http://127.0.0.1:11434"
    raise ValueError(f"Unknown provider: {provider_name}")


def require_supported(provider_name: str) -> str:
    normalized = provider_name.lower()
    if normalized not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"Unknown provider: {normalized}")
    return normalized


def build_provider_settings(provider_name: str) -> tuple[dict[str, str], str]:
    default_model, api_key_env, base_url = provider_defaults(provider_name)
    click.echo(f"\n=== Adding {provider_name} provider ===")
    settings = {
        "default_model": click.prompt("Default model", default=default_model),
    }
    if base_url is not None:
        settings["base_url"] = click.prompt("Base URL", default=base_url)
    env_var = ""
    if api_key_env:
        env_var = click.prompt("API key environment variable", default=api_key_env)
        settings["api_key_env"] = env_var
    return settings, env_var


def init_task_config(config: dict) -> dict:
    task = config.setdefault("task", {})
    if not isinstance(task, dict):
        raise ValueError("task config must be a mapping")
    task.setdefault("allowed_commands", list(_DEFAULT_TASK_COMMANDS))
    task.setdefault("max_iterations", 20)
    task.setdefault("default_timeout", 60)
    task.setdefault("default_workdir", None)
    return task


def get_task_prompts_dir() -> Path:
    from common.core.paths import get_fastmarket_dir

    prompts_dir = get_fastmarket_dir() / "task_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


def get_tools_doc_prompts_dir() -> Path:
    from common.core.paths import get_fastmarket_dir

    prompts_dir = get_fastmarket_dir() / "tools_doc_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


def run_interactive_wizard(config_path: Path, config: dict) -> None:
    click.echo("=== prompt-agent Setup Wizard ===\n")
    if config.get("providers"):
        click.echo("You already have providers configured:")
        for name in config["providers"].keys():
            marker = " (default)" if name == config.get("default_provider") else ""
            click.echo(f"  - {name}{marker}")
        if not click.confirm("\nDo you want to add another provider?", default=False):
            click.echo("\nSetup complete. Use 'prompt setup --help' for more options.")
            return

    click.echo("\nWhich LLM provider do you want to add?")
    click.echo("  1. Anthropic (Claude)")
    click.echo("  2. OpenAI (GPT)")
    click.echo("  3. OpenAI-compatible")
    click.echo("  4. Ollama")
    choice = click.prompt("Enter choice", type=click.Choice(["1", "2", "3", "4"]))
    provider_map = {
        "1": "anthropic",
        "2": "openai",
        "3": "openai-compatible",
        "4": "ollama",
    }
    provider_name = provider_map[choice]
    click.echo(f"\n--- {provider_name} configuration ---")
    settings, env_var = build_provider_settings(provider_name)

    config["providers"][provider_name] = settings
    if not config.get("default_provider"):
        config["default_provider"] = provider_name
    save_config(config_path, config)

    click.echo("\n✓ Setup complete!")
    click.echo(f"\nConfiguration saved to: {config_path}")
    if env_var:
        click.echo("\nDon't forget to set environment variable:")
        click.echo(f"  export {env_var}=your-api-key")
    click.echo("\nYou can add more providers with:")
    click.echo("  prompt setup providers-add <name>")


def run_default_editor(prompt_file: Path) -> None:
    editor = (
        subprocess.run(
            ["git", "var", "GIT_EDITOR"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or subprocess.run(
            ["sed", "-n", "s/^.*EDITOR.//p", "/etc/environment"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "nano"
    )
    subprocess.run([editor, str(prompt_file)], check=True)
