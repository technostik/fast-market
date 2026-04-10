from __future__ import annotations

import sys
import click
import yaml
from pathlib import Path

from common.core.yaml_utils import dump_yaml

from common.core.config import (
    load_common_config,
    load_llm_config,
    save_common_config,
    save_llm_config,
    ConfigError,
)
from common.core.paths import (
    get_common_config_path,
    get_llm_config_path,
    get_tool_config_path,
)
from commands.completion import (
    AvailableProviderParamType,
    ProviderParamType,
    ShellType,
    PathParamType,
)
from commands.setup.workdir import register as workdir_register

_PROVIDERS = {
    "anthropic": {
        "model": "claude-sonnet-4-20250514",
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url": None,
    },
    "openai": {
        "model": "gpt-4",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
    },
    "openai-compatible": {
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_COMPATIBLE_API_KEY",
        "base_url": "https://api.openai.com/v1",
    },
    "ollama": {
        "model": "llama3.2",
        "api_key_env": None,
        "base_url": "http://127.0.0.1:11434",
    },
}


def register():
    @click.group("toolsetup", invoke_without_command=True)
    @click.option("--show", "-s", is_flag=True, help="Show current config")
    @click.option("--show-path", "-p", is_flag=True, help="Show config file paths")
    @click.pass_context
    def setup_cmd(ctx, show, show_path):
        """Configure fast-market global settings.

        Manages common/config.yaml (workdir) and common/llm/config.yaml (LLM providers).
        Run with no arguments for the interactive wizard.
        """
        ctx.ensure_object(dict)

        if show_path:
            click.echo("Project config:")
            click.echo(f"  common: {get_common_config_path()}")
            click.echo(f"  llm:    {get_llm_config_path()}")
            click.echo("XDG config:")
            click.echo(f"  aliases:    ~/.config/fast-market/aliases.yaml")
            click.echo(f"  <tool>:     ~/.config/fast-market/{{tool}}/config.yaml")
            return

        if show:
            _show_config()
            return

        if ctx.invoked_subcommand is None:
            _run_wizard()

    @setup_cmd.group("llm")
    def llm_group():
        """Manage LLM provider configuration."""
        pass

    @llm_group.command("list")
    def llm_list():
        """List configured providers."""
        config = load_llm_config()
        providers = config.get("providers", {})
        default = config.get("default_provider", "")
        if not providers:
            click.echo("No providers configured. Run: toolsetup")
            return
        for name, settings in sorted(providers.items()):
            marker = " (default)" if name == default else ""
            click.echo(f"  {name}{marker}")
            click.echo(f"    model: {settings.get('model', '')}")
            if settings.get("base_url"):
                click.echo(f"    base_url: {settings['base_url']}")
            if settings.get("api_key_env"):
                click.echo(f"    api_key_env: {settings['api_key_env']}")

    @llm_group.command("add")
    @click.argument("provider", type=AvailableProviderParamType())
    def llm_add(provider):
        """Add or reconfigure a provider."""
        config = load_llm_config()
        settings = _prompt_provider_settings(provider)
        config.setdefault("providers", {})[provider] = settings
        if not config.get("default_provider"):
            config["default_provider"] = provider
            click.echo(f"Set {provider} as default provider.")
        save_llm_config(config)
        click.echo(f"Provider '{provider}' configured.")
        _print_env_reminder(provider, settings)

    @llm_group.command("remove")
    @click.argument("provider", type=ProviderParamType())
    def llm_remove(provider):
        """Remove a provider."""
        config = load_llm_config()
        providers = config.get("providers", {})
        if provider not in providers:
            click.echo(f"Provider not configured: {provider}", err=True)
            sys.exit(1)
        del providers[provider]
        if config.get("default_provider") == provider:
            remaining = list(providers)
            config["default_provider"] = remaining[0] if remaining else ""
            if remaining:
                click.echo(f"New default provider: {remaining[0]}")
        save_llm_config(config)
        click.echo(f"Provider '{provider}' removed.")

    @llm_group.command("set-default")
    @click.argument("provider", type=ProviderParamType())
    def llm_set_default(provider):
        """Set the default LLM provider."""
        config = load_llm_config()
        providers = config.get("providers", {})
        if provider not in providers:
            click.echo(f"Provider not configured: {provider}", err=True)
            click.echo(f"Add it first: toolsetup llm add {provider}", err=True)
            sys.exit(1)
        config["default_provider"] = provider
        save_llm_config(config)
        click.echo(f"Default provider set to: {provider}")

    @setup_cmd.command("path")
    @click.option(
        "--common", "path_type", flag_value="common", help="Show common config path"
    )
    @click.option("--llm", "path_type", flag_value="llm", help="Show LLM config path")
    @click.pass_context
    def show_path(ctx, path_type):
        """Show config file paths."""
        common_path = get_common_config_path()
        llm_path = get_llm_config_path()

        if path_type == "common":
            click.echo(common_path)
        elif path_type == "llm":
            click.echo(llm_path)
        else:
            click.echo(f"common: {common_path}")
            click.echo(f"llm:    {llm_path}")

    @setup_cmd.command("workdir")
    @click.argument("path", type=PathParamType(), required=False)
    def set_workdir(path):
        """Get or set the global default working directory."""
        config = load_common_config()
        if path is None:
            current = config.get("workdir")
            click.echo(current or "(not set)")
            return
        config["workdir"] = path
        save_common_config(config)
        click.echo(f"Default workdir set to: {path}")

    # Register workdir subgroup
    workdir_cmd = workdir_register()
    setup_cmd.add_command(workdir_cmd, name="workdir")

    @setup_cmd.command("clean-workdir")
    @click.option(
        "--force",
        "-f",
        is_flag=True,
        help="Skip confirmation prompt",
    )
    @click.option(
        "--all",
        "-a",
        is_flag=True,
        help="Also remove subdirectories and hidden files",
    )
    def clean_workdir(force, all):
        """Clean the global default working directory."""
        config = load_common_config()
        workdir = config.get("workdir")

        if not workdir:
            click.echo("No workdir configured. Run: toolsetup workdir <path>")
            return

        workdir_path = Path(workdir).expanduser().resolve()

        if not workdir_path.exists():
            click.echo(f"Workdir does not exist: {workdir_path}")
            return

        if not force:
            click.echo(f"Workdir: {workdir_path}")
            if not click.confirm("Delete all files in workdir?"):
                click.echo("Cancelled.")
                return

        removed_count = 0
        kept_count = 0

        for item in workdir_path.iterdir():
            if item.name.startswith("."):
                if all:
                    try:
                        if item.is_dir():
                            import shutil

                            shutil.rmtree(item)
                        else:
                            item.unlink()
                        removed_count += 1
                    except Exception as e:
                        click.echo(f"Error removing {item}: {e}")
                else:
                    kept_count += 1
                continue

            try:
                if item.is_dir():
                    if all:
                        import shutil

                        shutil.rmtree(item)
                        removed_count += 1
                    else:
                        kept_count += 1
                else:
                    item.unlink()
                    removed_count += 1
            except Exception as e:
                click.echo(f"Error removing {item}: {e}")

        click.echo(f"Removed {removed_count} items.")
        if kept_count > 0:
            click.echo(f"Kept {kept_count} items (directories or hidden files).")

    return setup_cmd


def _show_config():
    common_cfg = load_common_config()
    llm_cfg = load_llm_config()
    if not common_cfg and not llm_cfg:
        click.echo("No config found. Run: toolsetup")
        return
    click.echo("=== common/config.yaml ===")
    click.echo(dump_yaml(common_cfg, sort_keys=False))
    click.echo("=== common/llm/config.yaml ===")
    click.echo(dump_yaml(llm_cfg, sort_keys=False))


def _prompt_provider_settings(provider: str) -> dict:
    defaults = _PROVIDERS[provider]
    settings = {}
    settings["model"] = click.prompt("  Default model", default=defaults["model"])
    if defaults["base_url"] is not None:
        settings["base_url"] = click.prompt("  Base URL", default=defaults["base_url"])
    if defaults["api_key_env"] is not None:
        settings["api_key_env"] = click.prompt(
            "  API key env var", default=defaults["api_key_env"]
        )
    return settings


def _print_env_reminder(provider: str, settings: dict):
    env_var = settings.get("api_key_env")
    if env_var:
        click.echo(f"Remember to set: export {env_var}=your-key")


def _run_wizard():
    """Interactive first-time setup wizard."""
    llm_cfg = load_llm_config()
    common_cfg = load_common_config()

    click.echo("=== fast-market common setup ===\n")

    existing = llm_cfg.get("providers", {})
    if existing:
        click.echo("Current providers:")
        for name in existing:
            marker = " (default)" if name == llm_cfg.get("default_provider") else ""
            click.echo(f"  - {name}{marker}")
        if not click.confirm("\nAdd or reconfigure a provider?", default=False):
            click.echo("\nSetup complete. Use 'toolsetup --show' to review.")
            return

    click.echo("\nAvailable providers:")
    for i, name in enumerate(sorted(_PROVIDERS), 1):
        click.echo(f"  {i}. {name}")

    choices = [str(i) for i in range(1, len(_PROVIDERS) + 1)]
    choice = click.prompt("Choose provider", type=click.Choice(choices))
    provider = sorted(_PROVIDERS)[int(choice) - 1]

    click.echo(f"\n--- {provider} configuration ---")
    settings = _prompt_provider_settings(provider)

    llm_cfg.setdefault("providers", {})[provider] = settings
    if not llm_cfg.get("default_provider"):
        llm_cfg["default_provider"] = provider

    if click.confirm("\nSet a global default working directory?", default=False):
        workdir = click.prompt(
            "  Working directory", default=str(Path.home() / "fast-market-work")
        )
        common_cfg["workdir"] = workdir

    save_llm_config(llm_cfg)
    save_common_config(common_cfg)

    click.echo(f"\nConfig saved to:")
    click.echo(f"  LLM:  {get_llm_config_path()}")
    click.echo(f"  common: {get_common_config_path()}")
    _print_env_reminder(provider, settings)
    click.echo("\nYou can now use: prompt, task, skill")
    click.echo("Add more providers: toolsetup llm add <provider>")
