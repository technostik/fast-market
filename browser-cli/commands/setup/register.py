from __future__ import annotations

import click
from commands.base import CommandManifest
from common.core.paths import get_tool_config_path


_DEFAULT_CONFIG = {
    "browser": "google-chrome",
    "cdp_port": 9222,
    "user_data_dir": "~/.chrome-debug-profile",
    "extra_args": [],
}


def _load_config() -> dict:
    config_path = get_tool_config_path("browser")
    if config_path.exists():
        import yaml
        existing = yaml.safe_load(config_path.read_text()) or {}
        # Merge defaults: keep user values, fill in missing defaults
        return {**_DEFAULT_CONFIG, **existing}
    return dict(_DEFAULT_CONFIG)


def _save_config(config: dict) -> None:
    from common.core.yaml_utils import dump_yaml
    config_path = get_tool_config_path("browser")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(dump_yaml(config, sort_keys=False))


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup")
    def setup_group():
        """Edit browser CLI configuration."""
        pass

    @setup_group.command("edit")
    def setup_edit():
        """Open the browser config.yaml in the default editor."""
        from common.cli.helpers import open_editor

        config_path = get_tool_config_path("browser")
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write defaults if file doesn't exist
        if not config_path.exists():
            _save_config(_DEFAULT_CONFIG)

        open_editor(config_path)
        click.echo(f"Config saved to: {config_path}", err=True)

    @setup_group.command("reset")
    def setup_reset():
        """Reset browser config to default values."""
        config_path = get_tool_config_path("browser")

        if config_path.exists():
            backup = config_path.with_suffix(".yaml.bak")
            config_path.rename(backup)
            click.echo(f"Backed up old config to: {backup}", err=True)

        _save_config(_DEFAULT_CONFIG)
        click.echo(f"Config reset to defaults at: {config_path}", err=True)

    @setup_group.command("show")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format.",
    )
    def setup_show(fmt: str):
        """Show the current browser configuration."""
        from commands.helpers import out

        config = _load_config()
        out(config, fmt)

    @setup_group.command("show-path")
    def setup_show_path():
        """Show the path to the browser config file."""
        config_path = get_tool_config_path("browser")
        click.echo(str(config_path))

    return CommandManifest(
        name="setup",
        click_command=setup_group,
    )
