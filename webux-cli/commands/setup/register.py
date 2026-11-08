from __future__ import annotations

import shutil

import click
import yaml

from commands.base import CommandManifest
from common.core.config import load_tool_config, save_tool_config
from common.core.paths import get_tool_config_path
from common.core.profile import SHARED
from common.webux.theme import (
    DEFAULT_THEME,
    THEME_NAMES,
    is_valid_profile_color,
    resolve_theme,
)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup")
    def setup_group() -> None:
        """Manage webux setup and configuration."""
        pass

    @setup_group.command("show")
    def show_cmd() -> None:
        """Show current config as YAML."""
        config_path = get_tool_config_path("webux")
        if config_path.exists():
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {}
        click.echo(yaml.dump(config, default_flow_style=False, sort_keys=False).strip())

    @setup_group.command("reset")
    def reset_cmd() -> None:
        """Back up existing config and write a fresh empty config."""
        config_path = get_tool_config_path("webux")
        if config_path.exists():
            backup_path = config_path.with_suffix(".yaml.bak")
            shutil.copy2(config_path, backup_path)
            click.echo(f"Backed up existing config to {backup_path}")
        config_path.write_text("{}\n")
        click.echo(f"Reset config to empty dict at {config_path}")

    @setup_group.command("show-path")
    def show_path_cmd() -> None:
        """Print the config file path."""
        click.echo(str(get_tool_config_path("webux")))

    @setup_group.group("theme")
    def theme_group() -> None:
        """Manage the default webux theme (dark|light|blue)."""
        pass

    @theme_group.command("show")
    def theme_show_cmd() -> None:
        """Print the configured default theme and available themes."""
        config = load_tool_config("webux")
        click.echo(f"theme: {resolve_theme(config)}")
        click.echo(f"available: {', '.join(THEME_NAMES)}")
        click.echo(f"config_path: {get_tool_config_path('webux')}")

    @theme_group.command("set")
    @click.argument("name", type=click.Choice(list(THEME_NAMES)))
    def theme_set_cmd(name: str) -> None:
        """Persist the default theme (used on first paint; browser can override)."""
        config = load_tool_config("webux")
        config["theme"] = name
        save_tool_config("webux", config)
        click.echo(f"theme set to {name} (default was {DEFAULT_THEME})")

    # ── Profile colours ─────────────────────────────────────────────────
    # Written to the _shared profile so the map applies whatever the active
    # profile is. Without an entry, hues are evenly spaced by sorted name.

    def _shared_webux_config_path():
        return get_tool_config_path("webux", profile=SHARED)

    def _read_shared_webux_config() -> dict:
        path = _shared_webux_config_path()
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    def _write_shared_webux_config(config: dict) -> None:
        path = _shared_webux_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(config, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    @setup_group.group("profile-color")
    def profile_color_group() -> None:
        """Force the background tone of a profile (default: auto, per hue)."""
        pass

    @profile_color_group.command("show")
    def profile_color_show_cmd() -> None:
        """Show the configured profile colour map."""
        config = _read_shared_webux_config()
        colors = config.get("profile_colors") or {}
        if not colors:
            click.echo("(no explicit colours — tones are auto-assigned by hue)")
        else:
            click.echo(yaml.dump(colors, default_flow_style=False, sort_keys=True).strip())
        click.echo(f"config_path: {_shared_webux_config_path()}")

    @profile_color_group.command("set")
    @click.argument("profile")
    @click.argument("color")
    def profile_color_set_cmd(profile: str, color: str) -> None:
        """Set PROFILE's background colour, e.g. '#7c3aed'."""
        if not is_valid_profile_color(color):
            raise click.BadParameter(
                f"invalid colour {color!r}: use #rgb or #rrggbb"
            )
        config = _read_shared_webux_config()
        colors = config.get("profile_colors")
        if not isinstance(colors, dict):
            colors = {}
        colors[profile] = color
        config["profile_colors"] = colors
        _write_shared_webux_config(config)
        # Show the derived tone so the effect is obvious.
        click.echo(f"{profile}: {color}")
        click.echo(f"path: {_shared_webux_config_path()}")

    @profile_color_group.command("clear")
    @click.argument("profile")
    def profile_color_clear_cmd(profile: str) -> None:
        """Remove PROFILE's forced colour (back to the auto hue)."""
        config = _read_shared_webux_config()
        colors = config.get("profile_colors")
        if isinstance(colors, dict) and profile in colors:
            del colors[profile]
            config["profile_colors"] = colors
            _write_shared_webux_config(config)
            click.echo(f"cleared colour for {profile}")
        else:
            click.echo(f"no explicit colour for {profile}")

    @profile_color_group.command("tone")
    def profile_color_tone_cmd() -> None:
        """Preview the effective tone for every profile."""
        from common.core.paths import get_profiles_config_base
        from common.webux.theme import profile_tones

        base = get_profiles_config_base()
        names = sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []
        overrides = _read_shared_webux_config().get("profile_colors") or {}
        tones = profile_tones(names, overrides)
        for name in names:
            tone = tones[name]
            click.echo(
                f"{name}: bg={tone['bg']} border={tone['border']} accent={tone['accent']}"
            )

    return CommandManifest(name="setup", click_command=setup_group)
