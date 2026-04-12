from __future__ import annotations

import os
import shutil
import sys
import subprocess
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
    get_agent_config_path,
    get_aliases_path,
    get_youtube_config_path,
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

    @setup_cmd.command("edit")
    @click.option("--llm", "-l", "edit_llm", is_flag=True, help="Edit LLM config (common/llm/config.yaml)")
    @click.option("--common", "-c", "edit_common", is_flag=True, help="Edit common config (common/config.yaml)")
    def edit_config(edit_llm, edit_common):
        """Open config file(s) in your editor.

        By default, opens common/config.yaml.
        Use --llm to open common/llm/config.yaml.
        """
        if edit_llm:
            config_path = get_llm_config_path()
        else:
            config_path = get_common_config_path()

        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.write_text("", encoding="utf-8")

        common_cfg = load_common_config()
        editor = common_cfg.get("default_editor") or os.environ.get("EDITOR", "nano")
        subprocess.run([editor, str(config_path)])

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

    @setup_cmd.command("reset")
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
    @click.option("--agent", "reset_agent", is_flag=True, help="Reset agent config only")
    @click.option("--common", "reset_common", is_flag=True, help="Reset common config only")
    @click.option("--llm", "reset_llm", is_flag=True, help="Reset LLM config only")
    def reset_config(force, reset_agent, reset_common, reset_llm):
        """Reset config files to defaults (backs up existing).

        By default, resets ALL config files.
        Use --agent, --common, or --llm to reset specific files.
        """
        xdg_config = Path.home() / ".config" / "fast-market"

        if not reset_agent and not reset_common and not reset_llm:
            reset_agent = True
            reset_common = True
            reset_llm = True

        targets = []
        if reset_common:
            targets.append(("common config", get_common_config_path()))
            targets.append(("LLM config", get_llm_config_path()))
        if reset_llm:
            llm_path = get_llm_config_path()
            if ("LLM config", llm_path) not in targets:
                targets.append(("LLM config", llm_path))
        if reset_agent:
            targets.append(("agent config", get_agent_config_path()))

        # Remove duplicates while preserving order
        seen = set()
        unique_targets = []
        for name, path in targets:
            if path not in seen:
                seen.add(path)
                unique_targets.append((name, path))

        if not force:
            click.echo("This will reset the following config files to defaults:")
            for name, path in unique_targets:
                click.echo(f"  {path}")
            if not click.confirm("Continue? (existing configs will be backed up)"):
                click.echo("Cancelled.")
                return

        for name, config_path in unique_targets:
            _backup_and_reset(config_path, name)

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

        # Ensure common configs exist
        _ensure_default_common()

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


def _backup_and_reset(config_path: Path, name: str) -> None:
    """Back up a config file and reset it to defaults."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        backup = config_path.with_suffix(f".bak")
        # Handle multiple backups
        counter = 1
        while backup.exists():
            backup = config_path.with_suffix(f".bak.{counter}")
            counter += 1
        shutil.copy2(str(config_path), str(backup))
        click.echo(f"Backed up {name} to: {backup}")

    # Write appropriate defaults based on config type
    common_config = get_common_config_path()
    llm_config = get_llm_config_path()

    if config_path.resolve() == common_config.resolve():
        # Common config: write workdir defaults
        default_content = dump_yaml({
            "workdir": str(Path.home() / "fast-market-work"),
            "workdir_root": str(Path.home() / "fast-market-work"),
            "workdir_prefix": "work-",
        }, sort_keys=False)
    elif config_path.resolve() == llm_config.resolve():
        # LLM config: write minimal working defaults
        default_content = dump_yaml({
            "default_provider": "ollama",
            "providers": {
                "ollama": {
                    "model": "llama3.2",
                    "base_url": "http://127.0.0.1:11434",
                }
            }
        }, sort_keys=False)
    else:
        default_content = ""

    config_path.write_text(default_content, encoding="utf-8")
    click.echo(f"Reset {name}: {config_path}")


def _ensure_default_common() -> None:
    """Create default common config files if they don't exist."""
    # Common config
    common_path = get_common_config_path()
    common_path.parent.mkdir(parents=True, exist_ok=True)
    if not common_path.exists():
        common_path.write_text(
            dump_yaml({"workdir": str(Path.home() / "fast-market-work")}, sort_keys=False),
            encoding="utf-8",
        )
        click.echo(f"  Created: {common_path}")

    # LLM config
    llm_path = get_llm_config_path()
    llm_path.parent.mkdir(parents=True, exist_ok=True)
    if not llm_path.exists():
        llm_path.write_text(
            dump_yaml({
                "default_provider": "ollama",
                "providers": {
                    "ollama": {
                        "model": "llama3.2",
                        "base_url": "http://127.0.0.1:11434",
                    }
                }
            }, sort_keys=False),
            encoding="utf-8",
        )
        click.echo(f"  Created: {llm_path}")

    # Agent config
    agent_path = get_agent_config_path()
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    if not agent_path.exists():
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
        agent_path.write_text(dump_yaml(agent_config, sort_keys=False), encoding="utf-8")
        click.echo(f"  Created: {agent_path}")

    # YouTube common config
    yt_path = get_youtube_config_path()
    yt_path.parent.mkdir(parents=True, exist_ok=True)
    if not yt_path.exists():
        yt_path.write_text(
            dump_yaml({
                "client_secret_path": "~/.config/fast-market/common/youtube/client_secret.json",
                "channel_id": "",
                "quota_limit": 10000,
            }, sort_keys=False),
            encoding="utf-8",
        )
        click.echo(f"  Created: {yt_path}")


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
            "default_check_interval": "5m",
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
