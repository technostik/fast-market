from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.core.config import _resolve_config_path, load_tool_config
from common.core.paths import get_tool_config
from core.task_prompt import TaskPromptConfig, DEFAULT_PROMPT_TEMPLATE

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


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("setup")
    @click.option("--list-providers", is_flag=True, help="List configured providers")
    @click.option(
        "--add-provider",
        help="Add a provider (anthropic, openai, openai-compatible, ollama)",
    )
    @click.option("--remove-provider", help="Remove a provider")
    @click.option("--set-default", help="Set default provider")
    @click.option("--show-config", is_flag=True, help="Show current configuration")
    @click.option(
        "--config-path", "show_config_path", is_flag=True, help="Show config file path"
    )
    @click.option(
        "--list-task-commands", is_flag=True, help="List task allowed commands"
    )
    @click.option("--add-task-command", help="Add a command to task whitelist")
    @click.option("--remove-task-command", help="Remove a command from task whitelist")
    @click.option(
        "--set-task-max-iterations", type=int, help="Set max iterations for task"
    )
    @click.option(
        "--set-task-timeout", type=int, help="Set default timeout (seconds) for task"
    )
    @click.option("--list-prompts", is_flag=True, help="List available task prompts")
    @click.option("--set-prompt", help="Set active task prompt by name")
    @click.option("--show-prompt", help="Show a specific prompt")
    @click.option("--edit-prompt", help="Edit a prompt in default editor")
    @click.option(
        "--import-prompt", type=click.Path(exists=True), help="Import prompt from YAML"
    )
    @click.pass_context
    def setup_cmd(
        ctx,
        list_providers,
        add_provider,
        remove_provider,
        set_default,
        show_config,
        show_config_path,
        list_task_commands,
        add_task_command,
        remove_task_command,
        set_task_max_iterations,
        set_task_timeout,
        list_prompts,
        set_prompt,
        show_prompt,
        edit_prompt,
        import_prompt,
    ):
        """Setup wizard for managing LLM providers and task configuration."""
        config_path = _resolve_config_path("prompt")
        config = _load_config(config_path)

        if list_task_commands:
            _list_task_config(config)
            return
        if add_task_command:
            _add_task_command(config_path, config, add_task_command)
            return
        if remove_task_command:
            _remove_task_command(config_path, config, remove_task_command)
            return
        if set_task_max_iterations is not None:
            _set_task_max_iterations(config_path, config, set_task_max_iterations)
            return
        if set_task_timeout is not None:
            _set_task_timeout(config_path, config, set_task_timeout)
            return
        if list_providers:
            _list_providers(config)
            return
        if show_config:
            click.echo(
                yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
            )
            return
        if show_config_path:
            click.echo(config_path)
            return
        if add_provider:
            _add_provider(config_path, config, add_provider)
            return
        if remove_provider:
            _remove_provider(config_path, config, remove_provider)
            return
        if set_default:
            _set_default(config_path, config, set_default)
            return
        if list_prompts:
            _list_task_prompts(config)
            return
        if set_prompt:
            _set_active_prompt(config_path, config, set_prompt)
            return
        if show_prompt:
            _show_prompt(show_prompt)
            return
        if edit_prompt:
            _edit_prompt(edit_prompt)
            return
        if import_prompt:
            _import_prompt(config, import_prompt)
            return

        _run_interactive_wizard(config_path, config)

    return CommandManifest(name="setup", click_command=setup_cmd)


def _load_config(config_path: Path) -> dict:
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


def _save_config(config_path: Path, config: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _provider_defaults(provider_name: str) -> tuple[str, str, str | None]:
    if provider_name == "anthropic":
        return "claude-sonnet-4-20250514", "ANTHROPIC_API_KEY", None
    if provider_name == "openai":
        return "gpt-4", "OPENAI_API_KEY", None
    if provider_name == "openai-compatible":
        return "gpt-4o-mini", "OPENAI_COMPATIBLE_API_KEY", "https://api.openai.com/v1"
    if provider_name == "ollama":
        return "llama3.2", "", "http://127.0.0.1:11434"
    raise ValueError(f"Unknown provider: {provider_name}")


def _require_supported(provider_name: str) -> str:
    normalized = provider_name.lower()
    if normalized not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"Unknown provider: {normalized}")
    return normalized


def _build_provider_settings(provider_name: str) -> tuple[dict[str, str], str]:
    default_model, api_key_env, base_url = _provider_defaults(provider_name)
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


def _list_providers(config: dict) -> None:
    providers = config.get("providers", {})
    if not providers:
        click.echo("No providers configured.")
        return
    click.echo("Configured providers:")
    for name, settings in providers.items():
        default_marker = " (default)" if name == config.get("default_provider") else ""
        click.echo(f"  - {name}{default_marker}")
        click.echo(f"    Model: {settings.get('default_model', 'N/A')}")
        if settings.get("base_url"):
            click.echo(f"    Base URL: {settings['base_url']}")
        if settings.get("api_key_env"):
            click.echo(f"    API Key Env: {settings['api_key_env']}")


def _add_provider(config_path: Path, config: dict, provider_name: str) -> None:
    try:
        normalized = _require_supported(provider_name)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        click.echo("Supported: anthropic, openai, openai-compatible, ollama", err=True)
        sys.exit(1)

    settings, env_var = _build_provider_settings(normalized)
    config["providers"][normalized] = settings
    if not config.get("default_provider"):
        config["default_provider"] = normalized
        click.echo(f"\nSet {normalized} as default provider")
    _save_config(config_path, config)
    click.echo(f"\n✓ Added {normalized} provider")
    if env_var:
        click.echo(f"\nDon't forget to set {env_var} environment variable!")


def _remove_provider(config_path: Path, config: dict, provider_name: str) -> None:
    normalized = provider_name.lower()
    if normalized not in config.get("providers", {}):
        click.echo(f"Provider not configured: {normalized}", err=True)
        sys.exit(1)
    del config["providers"][normalized]
    if config.get("default_provider") == normalized:
        remaining = list(config["providers"].keys())
        config["default_provider"] = remaining[0] if remaining else ""
        if remaining:
            click.echo(f"Updated default provider to: {remaining[0]}")
    _save_config(config_path, config)
    click.echo(f"✓ Removed {normalized} provider")


def _set_default(config_path: Path, config: dict, provider_name: str) -> None:
    normalized = provider_name.lower()
    if normalized not in config.get("providers", {}):
        click.echo(f"Provider not configured: {normalized}", err=True)
        click.echo(
            f"Add it first with: prompt setup --add-provider {normalized}", err=True
        )
        sys.exit(1)
    config["default_provider"] = normalized
    _save_config(config_path, config)
    click.echo(f"✓ Set default provider to: {normalized}")


def _run_interactive_wizard(config_path: Path, config: dict) -> None:
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
    settings, env_var = _build_provider_settings(provider_name)

    config["providers"][provider_name] = settings
    if not config.get("default_provider"):
        config["default_provider"] = provider_name
    _save_config(config_path, config)

    click.echo("\n✓ Setup complete!")
    click.echo(f"\nConfiguration saved to: {config_path}")
    if env_var:
        click.echo("\nDon't forget to set environment variable:")
        click.echo(f"  export {env_var}=your-api-key")
    click.echo("\nYou can add more providers with:")
    click.echo("  prompt setup --add-provider <name>")


def _init_task_config(config: dict) -> dict:
    """Ensure task config exists and return it."""
    task = config.setdefault("task", {})
    if not isinstance(task, dict):
        raise ValueError("task config must be a mapping")
    task.setdefault("allowed_commands", list(_DEFAULT_TASK_COMMANDS))
    task.setdefault("max_iterations", 20)
    task.setdefault("default_timeout", 60)
    return task


def _list_task_config(config: dict) -> None:
    task = _init_task_config(config)
    click.echo("Task configuration:")
    click.echo(f"  Max iterations: {task.get('max_iterations', 20)}")
    click.echo(f"  Default timeout: {task.get('default_timeout', 60)}s")
    click.echo(f"  Allowed commands:")
    for cmd in sorted(task.get("allowed_commands", [])):
        click.echo(f"    - {cmd}")


def _add_task_command(config_path: Path, config: dict, command: str) -> None:
    task = _init_task_config(config)
    allowed = set(task.get("allowed_commands", []))
    if command in allowed:
        click.echo(f"Command already allowed: {command}")
        return
    allowed.add(command)
    task["allowed_commands"] = sorted(allowed)
    _save_config(config_path, config)
    click.echo(f"✓ Added '{command}' to task allowed commands")


def _remove_task_command(config_path: Path, config: dict, command: str) -> None:
    task = _init_task_config(config)
    allowed = set(task.get("allowed_commands", []))
    if command not in allowed:
        click.echo(f"Command not in whitelist: {command}", err=True)
        sys.exit(1)
    allowed.discard(command)
    task["allowed_commands"] = sorted(allowed)
    _save_config(config_path, config)
    click.echo(f"✓ Removed '{command}' from task allowed commands")


def _set_task_max_iterations(config_path: Path, config: dict, max_iter: int) -> None:
    if max_iter < 1:
        click.echo("Max iterations must be at least 1", err=True)
        sys.exit(1)
    task = _init_task_config(config)
    task["max_iterations"] = max_iter
    _save_config(config_path, config)
    click.echo(f"✓ Set task max iterations to {max_iter}")


def _set_task_timeout(config_path: Path, config: dict, timeout: int) -> None:
    if timeout < 1:
        click.echo("Timeout must be at least 1 second", err=True)
        sys.exit(1)
    task = _init_task_config(config)
    task["default_timeout"] = timeout
    _save_config(config_path, config)
    click.echo(f"✓ Set task default timeout to {timeout}s")


def _get_prompts_dir() -> Path:
    """Get prompts directory path."""
    from common.core.paths import get_fastmarket_dir

    prompts_dir = get_fastmarket_dir() / "task_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


def _list_task_prompts(config: dict) -> None:
    """List available task prompts."""
    prompts_dir = _get_prompts_dir()
    active = config.get("task", {}).get("active_prompt", "default")

    click.echo("Available task prompts:")

    marker = "*" if active == "default" else " "
    click.echo(f" {marker} default (built-in)")

    for file in prompts_dir.glob("*.yaml"):
        prompt_config = TaskPromptConfig.from_yaml(file)
        if prompt_config:
            marker = "*" if active == prompt_config.name else " "
            desc = (
                f" - {prompt_config.description}" if prompt_config.description else ""
            )
            click.echo(f" {marker} {prompt_config.name}{desc}")


def _set_active_prompt(config_path: Path, config: dict, prompt_name: str) -> None:
    """Set the active task prompt."""
    if prompt_name == "default":
        config.setdefault("task", {})["active_prompt"] = prompt_name
        _save_config(config_path, config)
        click.echo(f"✓ Active task prompt set to: default (built-in)")
        return

    prompts_dir = _get_prompts_dir()
    prompt_file = prompts_dir / f"{prompt_name}.yaml"
    if not prompt_file.exists():
        click.echo(f"Error: Prompt '{prompt_name}' not found", err=True)
        sys.exit(1)

    config.setdefault("task", {})["active_prompt"] = prompt_name
    _save_config(config_path, config)
    click.echo(f"✓ Active task prompt set to: {prompt_name}")


def _show_prompt(prompt_name: str) -> None:
    """Show a specific prompt's configuration."""
    if prompt_name == "default":
        click.echo(f"=== Default Prompt ===")
        click.echo(f"Name: default")
        click.echo(f"Description: Built-in default task prompt")
        click.echo(f"\nTemplate:\n")
        click.echo(DEFAULT_PROMPT_TEMPLATE)
        return

    prompts_dir = _get_prompts_dir()
    prompt_file = prompts_dir / f"{prompt_name}.yaml"
    if not prompt_file.exists():
        click.echo(f"Error: Prompt '{prompt_name}' not found", err=True)
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


def _edit_prompt(prompt_name: str) -> None:
    """Edit a prompt in the default editor."""
    prompts_dir = _get_prompts_dir()

    if prompt_name == "default":
        click.echo("Error: Cannot edit the built-in default prompt", err=True)
        sys.exit(1)

    prompt_file = prompts_dir / f"{prompt_name}.yaml"
    if not prompt_file.exists():
        click.echo(f"Prompt '{prompt_name}' not found. Creating new prompt...")
        default_config = TaskPromptConfig(
            name=prompt_name,
            description="Custom task prompt",
            template=DEFAULT_PROMPT_TEMPLATE,
        )
        default_config.save(prompt_file)
        click.echo(f"Created: {prompt_file}")

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
    click.echo(f"✓ Edited prompt: {prompt_name}")


def _import_prompt(config: dict, import_path: str) -> None:
    """Import a prompt from a YAML file."""
    source_path = Path(import_path)
    prompt_config = TaskPromptConfig.from_yaml(source_path)

    if not prompt_config:
        click.echo(f"Error: Could not parse prompt file: {import_path}", err=True)
        sys.exit(1)

    errors = prompt_config.validate()
    if errors:
        click.echo(f"Error: Invalid prompt configuration:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    prompts_dir = _get_prompts_dir()
    target_file = prompts_dir / f"{prompt_config.name}.yaml"

    if target_file.exists():
        if not click.confirm(f"Prompt '{prompt_config.name}' exists. Overwrite?"):
            click.echo("Import cancelled.")
            return

    prompt_config.save(target_file)
    click.echo(f"✓ Imported prompt '{prompt_config.name}' to: {target_file}")
