from __future__ import annotations

import os
import shutil
import sys
import subprocess
import click
from pathlib import Path

from common.core.yaml_utils import dump_yaml

from common.core.config import (
    load_common_config,  # used by edit_config for editor resolution
)
from common.core.paths import (
    get_tool_config_path,
)
from commands.completion import (
    AvailableProviderParamType,
    ProviderParamType,
    PathParamType,
)
from commands.setup.workdir import register as workdir_register

# Import all plugins so they self-register
from commands.setup.plugins import all_plugins, get_plugin  # noqa: F401
from commands.setup.plugins import youtube as _yt_plugin  # noqa: F401
from commands.setup.plugins import llm as _llm_plugin  # noqa: F401
from commands.setup.plugins import agent as _agent_plugin  # noqa: F401
from commands.setup.plugins import workdir as _workdir_plugin  # noqa: F401

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
            for name, plugin in sorted(all_plugins().items()):
                click.echo(f"  {name:10s}: {plugin.config_path()}")
            click.echo("XDG config:")
            click.echo("  aliases:    ~/.config/fast-market/aliases.yaml")
            click.echo("  <tool>:     ~/.config/fast-market/{tool}/config.yaml")
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
        plugin = get_plugin("llm")
        config = plugin.load()
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
        plugin = get_plugin("llm")
        config = plugin.load()
        settings = _prompt_provider_settings(provider)
        config.setdefault("providers", {})[provider] = settings
        if not config.get("default_provider"):
            config["default_provider"] = provider
            click.echo(f"Set {provider} as default provider.")
        plugin.save(config)
        click.echo(f"Provider '{provider}' configured.")
        _print_env_reminder(provider, settings)

    @llm_group.command("remove")
    @click.argument("provider", type=ProviderParamType())
    def llm_remove(provider):
        """Remove a provider."""
        plugin = get_plugin("llm")
        config = plugin.load()
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
        plugin.save(config)
        click.echo(f"Provider '{provider}' removed.")

    @llm_group.command("set-default")
    @click.argument("provider", type=ProviderParamType())
    def llm_set_default(provider):
        """Set the default LLM provider."""
        plugin = get_plugin("llm")
        config = plugin.load()
        providers = config.get("providers", {})
        if provider not in providers:
            click.echo(f"Provider not configured: {provider}", err=True)
            click.echo(f"Add it first: toolsetup llm add {provider}", err=True)
            sys.exit(1)
        config["default_provider"] = provider
        plugin.save(config)
        click.echo(f"Default provider set to: {provider}")

    @setup_cmd.command("path")
    @click.option("--youtube", "path_type", flag_value="youtube", help="Show YouTube config path")
    @click.option(
        "--common", "path_type", flag_value="common", help="Show common config path (alias for --workdir)"
    )
    @click.option("--workdir", "path_type", flag_value="workdir", help="Show workdir config path")
    @click.option("--llm", "path_type", flag_value="llm", help="Show LLM config path")
    @click.option("--agent", "path_type", flag_value="agent", help="Show agent config path")
    @click.pass_context
    def show_path(ctx, path_type):
        """Show config file paths."""
        plugins_map = {
            "youtube": "youtube",
            "common": "workdir",
            "workdir": "workdir",
            "llm": "llm",
            "agent": "agent",
        }
        if path_type:
            plugin_name = plugins_map.get(path_type)
            if plugin_name:
                plugin = get_plugin(plugin_name)
                click.echo(plugin.config_path())
        else:
            for name, plugin in sorted(all_plugins().items()):
                click.echo(f"{name:10s}: {plugin.config_path()}")

    @setup_cmd.command("workdir")
    @click.argument("path", type=PathParamType(), required=False)
    def set_workdir(path):
        """Get or set the global default working directory."""
        plugin = get_plugin("workdir")
        config = plugin.load()
        if path is None:
            current = config.get("workdir")
            click.echo(current or "(not set)")
            return
        config["workdir"] = path
        plugin.save(config)
        click.echo(f"Default workdir set to: {path}")

    # Register workdir subgroup
    workdir_cmd = workdir_register()
    setup_cmd.add_command(workdir_cmd, name="workdir")

    @setup_cmd.command("edit")
    @click.option("--youtube", "-y", "edit_youtube", is_flag=True, help="Edit YouTube config")
    @click.option("--llm", "-l", "edit_llm", is_flag=True, help="Edit LLM config")
    @click.option("--workdir", "-w", "edit_workdir", is_flag=True, help="Edit workdir config (common/config.yaml)")
    @click.option("--common", "-c", "edit_common", is_flag=True, help="Alias for --workdir")
    @click.option("--agent", "-a", "edit_agent", is_flag=True, help="Edit agent config")
    def edit_config(edit_youtube, edit_llm, edit_workdir, edit_common, edit_agent):
        """Open config file(s) in your editor.

        By default, opens ALL config files.
        Use --youtube, --llm, --workdir, or --agent to open specific ones.
        """
        # --common is alias for --workdir
        if edit_common:
            edit_workdir = True

        selected = []
        if edit_youtube:
            selected.append("youtube")
        if edit_llm:
            selected.append("llm")
        if edit_workdir:
            selected.append("workdir")
        if edit_agent:
            selected.append("agent")

        # If nothing selected, edit all
        if not selected:
            selected = list(all_plugins().keys())

        common_cfg = load_common_config()
        editor = common_cfg.get("default_editor") or os.environ.get("EDITOR", "nano")

        for name in selected:
            plugin = get_plugin(name)
            plugin.ensure_exists()
            config_path = plugin.config_path()
            click.echo(f"Opening {plugin.display_name}: {config_path}")
            subprocess.run([editor, str(config_path)])

    @setup_cmd.command("show")
    @click.option("--youtube", "show_youtube", is_flag=True, help="Show YouTube config")
    @click.option("--llm", "show_llm", is_flag=True, help="Show LLM config")
    @click.option("--workdir", "show_workdir", is_flag=True, help="Show workdir config")
    @click.option("--common", "show_common", is_flag=True, help="Alias for --workdir")
    @click.option("--agent", "show_agent", is_flag=True, help="Show agent config")
    def show_config(show_youtube, show_llm, show_workdir, show_common, show_agent):
        """Show config file contents.

        By default, shows ALL config files.
        Use --youtube, --llm, --workdir, or --agent to show specific ones.
        """
        if show_common:
            show_workdir = True

        selected = []
        if show_youtube:
            selected.append("youtube")
        if show_llm:
            selected.append("llm")
        if show_workdir:
            selected.append("workdir")
        if show_agent:
            selected.append("agent")

        # If nothing selected, show all
        if not selected:
            selected = list(all_plugins().keys())

        first = True
        for name in selected:
            plugin = get_plugin(name)
            config = plugin.load()
            if not first:
                click.echo("")
            click.echo(f"=== {plugin.display_name} ({plugin.config_path()}) ===")
            if config:
                click.echo(dump_yaml(config, sort_keys=False))
            else:
                click.echo("(not configured)")
            first = False

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
        plugin = get_plugin("workdir")
        config = plugin.load()
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

    @setup_cmd.command("reset")
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
    @click.option("--youtube", "reset_youtube", is_flag=True, help="Reset YouTube config")
    @click.option("--agent", "reset_agent", is_flag=True, help="Reset agent config")
    @click.option("--workdir", "reset_workdir", is_flag=True, help="Reset workdir config")
    @click.option("--common", "reset_common", is_flag=True, help="Alias for --workdir")
    @click.option("--llm", "reset_llm", is_flag=True, help="Reset LLM config")
    def reset_config(force, reset_youtube, reset_agent, reset_workdir, reset_common, reset_llm):
        """Reset config files to defaults (backs up existing).

        By default, resets ALL config files.
        Use --youtube, --agent, --workdir, or --llm to reset specific files.
        """
        if reset_common:
            reset_workdir = True

        if not reset_youtube and not reset_agent and not reset_workdir and not reset_llm:
            reset_youtube = True
            reset_agent = True
            reset_workdir = True
            reset_llm = True

        targets = []
        if reset_workdir:
            targets.append(get_plugin("workdir"))
        if reset_llm:
            targets.append(get_plugin("llm"))
        if reset_agent:
            targets.append(get_plugin("agent"))
        if reset_youtube:
            targets.append(get_plugin("youtube"))

        if not force:
            click.echo("This will reset the following config files to defaults:")
            for plugin in targets:
                click.echo(f"  {plugin.config_path()}")
            if not click.confirm("Continue? (existing configs will be backed up)"):
                click.echo("Cancelled.")
                return

        for plugin in targets:
            _backup_and_reset_plugin(plugin)

        click.echo("\nAll selected configs reset to defaults.")

    @setup_cmd.command("reset-all")
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
    @click.option("--provider", "default_provider",
                  type=click.Choice(["anthropic", "openai", "ollama", "openai-compatible"]),
                  help="LLM provider to configure")
    @click.option("--workdir", "workdir_path",
                  type=str,
                  help="Default working directory")
    def reset_all(force, default_provider, workdir_path):
        """Create a fresh default config for all tools.

        Creates default config files for all fast-market tools so you
        only need to change values, not recreate structure.
        Existing configs are backed up before being overwritten.
        """
        if not force:
            click.echo("This will create default configs for all tools.")
            click.echo("Existing configs will be backed up and overwritten.")
            if not click.confirm("Continue?"):
                click.echo("Cancelled.")
                return

        # Ensure common configs exist via plugins
        for plugin in all_plugins().values():
            plugin.ensure_exists()

        # Create default tool configs
        tools = [
            "browser", "corpus", "image", "message", "monitor",
            "prompt", "skill", "tiktok", "webux", "youtube",
        ]
        for tool in tools:
            _ensure_default_tool_config(tool, backup_existing=True)

        click.echo("Default configs created. Edit any config with:")
        click.echo("  <tool> setup edit")
        click.echo("Or:")
        click.echo("  <tool> setup --show-config  (to see current)")
        click.echo("  <tool> setup --show-config-path (to see path)")

    return setup_cmd


def _show_config():
    """Show all plugin configs."""
    first = True
    for name, plugin in sorted(all_plugins().items()):
        config = plugin.load()
        if not first:
            click.echo("")
        click.echo(f"=== {plugin.display_name} ({plugin.config_path()}) ===")
        if config:
            click.echo(dump_yaml(config, sort_keys=False))
        else:
            click.echo("(not configured)")
        first = False


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
    llm_plugin = get_plugin("llm")
    workdir_plugin = get_plugin("workdir")

    llm_cfg = llm_plugin.load()
    common_cfg = workdir_plugin.load()

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

    llm_plugin.save(llm_cfg)
    workdir_plugin.save(common_cfg)

    click.echo("\nConfig saved to:")
    click.echo(f"  LLM:    {llm_plugin.config_path()}")
    click.echo(f"  workdir: {workdir_plugin.config_path()}")
    _print_env_reminder(provider, settings)
    click.echo("\nYou can now use: prompt, task, skill")
    click.echo("Add more providers: toolsetup llm add <provider>")


def _backup_and_reset_plugin(plugin) -> None:
    """Back up a plugin's config file and reset it to defaults."""
    config_path = plugin.config_path()
    name = plugin.display_name

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        backup = config_path.with_suffix(".bak")
        counter = 1
        while backup.exists():
            backup = config_path.with_suffix(f".bak.{counter}")
            counter += 1
        shutil.copy2(str(config_path), str(backup))
        click.echo(f"Backed up {name} to: {backup}")

    plugin.save(plugin.default_config())
    click.echo(f"Reset {name}: {config_path}")


def _build_default_agent_config() -> str:
    """Return full agent config as YAML string with all defaults for the agentic loop."""
    from common.agent.prompts import (
        DEFAULT_AGENT_PROMPT_TEMPLATE,
        DEFAULT_SYSTEM_COMMANDS,
        default_fastmarket_tools_dict,
        DEFAULT_EVALUATION_PROMPT,
        DEFAULT_PLAN_PROMPT,
        DEFAULT_PREPARATION_PROMPT,
        DEFAULT_COMMAND_DOCS_TEMPLATES,
    )
    from common.learn import SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE

    agent_config = {
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
            "templates": dict(DEFAULT_COMMAND_DOCS_TEMPLATES),
        },
        "preparation_prompt": DEFAULT_PREPARATION_PROMPT,
        "evaluation_prompt": DEFAULT_EVALUATION_PROMPT,
        "plan_prompt": DEFAULT_PLAN_PROMPT,
        "skill_from_description_prompt": SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE,
    }
    return dump_yaml(agent_config, sort_keys=False)


def _ensure_default_tool_config(tool: str, backup_existing: bool = False) -> None:
    """Create a default config for a tool if it doesn't exist."""
    config_path = get_tool_config_path(tool)

    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        if backup_existing:
            backup = config_path.with_suffix(".bak")
            counter = 1
            while backup.exists():
                backup = config_path.with_suffix(f".bak.{counter}")
                counter += 1
            shutil.copy2(str(config_path), str(backup))

    defaults = _get_tool_default_config(tool)
    if defaults is not None:
        config_path.write_text(dump_yaml(defaults, sort_keys=False), encoding="utf-8")
        if backup_existing:
            click.echo(f"  Reset: {config_path}")


def _get_tool_default_config(tool: str) -> dict | None:
    """Return default config for a tool, or None for empty config."""
    defaults = {
        "browser": {
            "browser": "google-chrome",
            "cdp_port": 9222,
            "user_data_dir": "~/.chrome-debug-profile",
            "extra_args": [],
        },
        "image": {
            "default_engine": "flux2",
            "engines": {
                "flux2": {
                    "model_path": "./flux2-klein-4b",
                    "torch_dtype": "bfloat16",
                    "local_files_only": True,
                }
            },
            "default_width": 1024,
            "default_height": 1024,
            "default_guidance_scale": 1.0,
            "default_num_inference_steps": 4,
            "default_output_format": "PNG",
            "output_dir": ".",
            "cache_pipeline": True,
        },
        "message": {
            "telegram": {
                "bot_token": "",
                "allowed_chat_id": None,
                "default_timeout": 300,
                "default_wait_for_ack": False,
            }
        },
        "monitor": {
            "default_slowdown": "5m",
            "sources": [],
            "actions": [],
            "rules": [],
        },
        "tiktok": {
            "tiktok": {
                "# Path to TikTokAutoUploader installation": None,
                "# tiktok_auto_uploader_path": "/path/to/TikTokAutoUploader",
                "# TikTok username for uploads": None,
                "# username": "your_username",
            }
        },
        "youtube": {
            "youtube": {
                "channel_id": "",
                "quota_limit": 10000,
            }
        },
        "webux": {},
        "corpus": {},
        "prompt": {},
        "skill": {},
    }
    return defaults.get(tool)
