from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.core.paths import get_tool_config

_SUPPORTED_PROVIDERS = {"anthropic", "openai", "openai-compatible", "ollama"}


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
    @click.pass_context
    def setup_cmd(ctx, list_providers, add_provider, remove_provider, set_default, show_config):
        """Setup wizard for managing LLM providers."""
        config_path = get_tool_config("prompt")
        config = _load_config(config_path)

        if list_providers:
            _list_providers(config)
            return
        if show_config:
            click.echo(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
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
        click.echo(f"Add it first with: prompt setup --add-provider {normalized}", err=True)
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
    provider_map = {"1": "anthropic", "2": "openai", "3": "openai-compatible", "4": "ollama"}
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
