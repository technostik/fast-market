from __future__ import annotations

import sys

import click

from common.core.config import _resolve_config_path
from commands.setup import (
    load_config,
    save_config,
    require_supported,
    build_provider_settings,
)


def create_providers_group() -> click.Group:
    @click.group("providers")
    def providers():
        """Manage LLM providers."""
        pass

    @providers.command("list")
    def list_providers():
        """List configured providers."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        providers = config.get("providers", {})
        if not providers:
            click.echo("No providers configured.")
            return
        click.echo("Configured providers:")
        for name, settings in providers.items():
            default_marker = (
                " (default)" if name == config.get("default_provider") else ""
            )
            click.echo(f"  - {name}{default_marker}")
            click.echo(f"    Model: {settings.get('default_model', 'N/A')}")
            if settings.get("base_url"):
                click.echo(f"    Base URL: {settings['base_url']}")
            if settings.get("api_key_env"):
                click.echo(f"    API Key Env: {settings['api_key_env']}")

    @providers.command("add")
    @click.argument("name")
    def add_provider(name: str):
        """Add a provider."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        try:
            normalized = require_supported(name)
        except ValueError as exc:
            click.echo(str(exc), err=True)
            click.echo(
                "Supported: anthropic, openai, openai-compatible, ollama", err=True
            )
            sys.exit(1)

        settings, env_var = build_provider_settings(normalized)
        config["providers"][normalized] = settings
        if not config.get("default_provider"):
            config["default_provider"] = normalized
            click.echo(f"\nSet {normalized} as default provider")
        save_config(config_path, config)
        click.echo(f"\n✓ Added {normalized} provider")
        if env_var:
            click.echo(f"\nDon't forget to set {env_var} environment variable!")

    @providers.command("remove")
    @click.argument("name")
    def remove_provider(name: str):
        """Remove a provider."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        normalized = name.lower()
        if normalized not in config.get("providers", {}):
            click.echo(f"Provider not configured: {normalized}", err=True)
            sys.exit(1)
        del config["providers"][normalized]
        if config.get("default_provider") == normalized:
            remaining = list(config["providers"].keys())
            config["default_provider"] = remaining[0] if remaining else ""
            if remaining:
                click.echo(f"Updated default provider to: {remaining[0]}")
        save_config(config_path, config)
        click.echo(f"✓ Removed {normalized} provider")

    @providers.command("set-default")
    @click.argument("name")
    def set_default(name: str):
        """Set default provider."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        normalized = name.lower()
        if normalized not in config.get("providers", {}):
            click.echo(f"Provider not configured: {normalized}", err=True)
            click.echo(
                f"Add it first with: prompt setup providers-add {normalized}", err=True
            )
            sys.exit(1)
        config["default_provider"] = normalized
        save_config(config_path, config)
        click.echo(f"✓ Set default provider to: {normalized}")

    return providers
