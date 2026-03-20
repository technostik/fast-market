from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.core.config import load_tool_config
from common.core.paths import get_tool_config
from core.config import get_default_config


_SUPPORTED_ENGINES = {"flux2"}


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("setup")
    @click.option("--list-engines", "-l", is_flag=True, help="List configured engines")
    @click.option(
        "--add-engine",
        "-a",
        type=click.Choice(["flux2"]),
        help="Add an engine (flux2)",
    )
    @click.option("--remove-engine", "-r", help="Remove an engine")
    @click.option("--set-default-engine", "-d", help="Set default engine")
    @click.option(
        "--set-model-path",
        "-m",
        help="Set model path for an engine (format: engine:path)",
    )
    @click.option("--set-defaults", "-s", is_flag=True, help="Set generation defaults")
    @click.option("--set-output-dir", "-o", help="Set default output directory")
    @click.option(
        "--show-config", "-c", is_flag=True, help="Show current configuration"
    )
    @click.option(
        "--show-config-path", "-p", is_flag=True, help="Show config file path"
    )
    @click.pass_context
    def setup_cmd(
        ctx,
        list_engines,
        add_engine,
        remove_engine,
        set_default_engine,
        set_model_path,
        set_defaults,
        set_output_dir,
        show_config,
        show_config_path,
    ):
        """Setup wizard for managing image-agent configuration."""
        config_path = get_tool_config("image")
        config = _load_config(config_path)

        if list_engines:
            _list_engines(config)
            return
        if show_config:
            click.echo(
                yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
            )
            return
        if show_config_path:
            click.echo(config_path)
            return
        if add_engine:
            _add_engine(config_path, config, add_engine)
            return
        if remove_engine:
            _remove_engine(config_path, config, remove_engine)
            return
        if set_default_engine:
            _set_default_engine(config_path, config, set_default_engine)
            return
        if set_model_path:
            _set_model_path(config_path, config, set_model_path)
            return
        if set_defaults:
            _set_defaults(config_path, config)
            return
        if set_output_dir:
            _set_output_dir(config_path, config, set_output_dir)
            return

        _run_interactive_wizard(config_path, config, plugin_manifests)

    return CommandManifest(name="setup", click_command=setup_cmd)


def _load_config(config_path: Path) -> dict:
    """Load config from file, return defaults if not exists."""
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if data and isinstance(data, dict):
            return data
    return get_default_config()


def _save_config(config_path: Path, config: dict) -> None:
    """Save config to file, creating directories as needed."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _require_supported(engine_name: str) -> str:
    """Normalize and validate engine name."""
    normalized = engine_name.lower()
    if normalized not in _SUPPORTED_ENGINES:
        raise ValueError(f"Unknown engine: {normalized}")
    return normalized


def _get_engine_defaults(engine_name: str) -> dict:
    """Return default config for an engine."""
    defaults = get_default_config()
    return defaults.get("engines", {}).get(engine_name, {})


def _list_engines(config: dict) -> None:
    """List configured engines."""
    engines = config.get("engines", {})
    default_engine = config.get("default_engine", "flux2")
    if not engines:
        click.echo("No engines configured.")
        return
    click.echo("Configured engines:")
    for name, settings in engines.items():
        marker = " (default)" if name == default_engine else ""
        click.echo(f"  - {name}{marker}")
        model_path = (
            settings.get("model_path", "N/A") if isinstance(settings, dict) else "N/A"
        )
        click.echo(f"    Model path: {model_path}")


def _add_engine(config_path: Path, config: dict, engine_name: str) -> None:
    """Add a new engine configuration."""
    try:
        normalized = _require_supported(engine_name)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        click.echo(f"Supported engines: {', '.join(_SUPPORTED_ENGINES)}", err=True)
        sys.exit(1)

    if "engines" not in config:
        config["engines"] = {}

    if normalized in config["engines"]:
        click.echo(f"Engine '{normalized}' already configured.")
        if not click.confirm("Update it?", default=True):
            return

    default_settings = _get_engine_defaults(normalized)
    click.echo(f"\n=== Adding {normalized} engine ===")
    model_path = click.prompt(
        "Model path",
        default=default_settings.get("model_path", "./flux2-klein-4b"),
    )

    engines = config.setdefault("engines", {})
    engines[normalized] = {
        "model_path": model_path,
        "torch_dtype": default_settings.get("torch_dtype", "bfloat16"),
        "local_files_only": default_settings.get("local_files_only", True),
    }

    if not config.get("default_engine"):
        config["default_engine"] = normalized
        click.echo(f"\nSet {normalized} as default engine")

    _save_config(config_path, config)
    click.echo(f"\n✓ Added {normalized} engine")
    click.echo(f"\nConfiguration saved to: {config_path}")

    if not Path(model_path).exists():
        click.echo("\nWarning: Model path does not exist yet.")
        click.echo("Download the model before using this engine.")


def _remove_engine(config_path: Path, config: dict, engine_name: str) -> None:
    """Remove an engine configuration."""
    normalized = engine_name.lower()
    engines = config.get("engines", {})

    if normalized not in engines:
        click.echo(f"Engine not configured: {normalized}", err=True)
        sys.exit(1)

    del engines[normalized]

    if config.get("default_engine") == normalized:
        remaining = list(engines.keys())
        config["default_engine"] = remaining[0] if remaining else ""
        if remaining:
            click.echo(f"Updated default engine to: {remaining[0]}")

    _save_config(config_path, config)
    click.echo(f"✓ Removed {normalized} engine")


def _set_default_engine(config_path: Path, config: dict, engine_name: str) -> None:
    """Set the default engine."""
    normalized = engine_name.lower()
    engines = config.get("engines", {})

    if normalized not in engines:
        click.echo(f"Engine not configured: {normalized}", err=True)
        sys.exit(1)

    config["default_engine"] = normalized
    _save_config(config_path, config)
    click.echo(f"✓ Set default engine to: {normalized}")


def _set_model_path(config_path: Path, config: dict, engine_path: str) -> None:
    """Set model path for an engine (format: engine:path)."""
    if ":" not in engine_path:
        click.echo(
            "Error: Use format 'engine:path' (e.g., flux2:/path/to/model)", err=True
        )
        sys.exit(1)

    engine_name, model_path = engine_path.split(":", 1)
    normalized = engine_name.lower()
    engines = config.get("engines", {})

    if normalized not in engines:
        click.echo(f"Engine not configured: {normalized}", err=True)
        sys.exit(1)

    engines[normalized]["model_path"] = model_path
    _save_config(config_path, config)
    click.echo(f"✓ Set {normalized} model path to: {model_path}")


def _set_defaults(config_path: Path, config: dict) -> None:
    """Interactively set default generation parameters."""
    click.echo("\n=== Setting default generation parameters ===\n")

    config["default_width"] = click.prompt(
        "Default width",
        default=config.get("default_width", 1024),
        type=int,
    )
    config["default_height"] = click.prompt(
        "Default height",
        default=config.get("default_height", 1024),
        type=int,
    )
    config["default_guidance_scale"] = click.prompt(
        "Default guidance scale",
        default=config.get("default_guidance_scale", 1.0),
        type=float,
    )
    config["default_num_inference_steps"] = click.prompt(
        "Default inference steps",
        default=config.get("default_num_inference_steps", 4),
        type=int,
    )
    config["default_output_format"] = click.prompt(
        "Default output format",
        default=config.get("default_output_format", "PNG"),
        type=click.Choice(["PNG", "JPEG", "WEBP"]),
    )

    seed_input = click.prompt(
        "Default seed (leave empty for random)",
        default="",
    )
    config["default_seed"] = int(seed_input) if seed_input.strip() else None

    _save_config(config_path, config)
    click.echo("\n✓ Default parameters saved")


def _set_output_dir(config_path: Path, config: dict, output_dir: str) -> None:
    """Set the default output directory."""
    config["output_dir"] = output_dir
    _save_config(config_path, config)
    click.echo(f"✓ Set output directory to: {output_dir}")


def _run_interactive_wizard(
    config_path: Path,
    config: dict,
    plugin_manifests: dict,
) -> None:
    """Run the interactive setup wizard."""
    click.echo("=== image-agent Setup Wizard ===\n")

    available_engines = list(plugin_manifests.keys()) if plugin_manifests else ["flux2"]

    while True:
        click.echo("\nWhat would you like to do?")
        click.echo("  1. Configure engines")
        click.echo("  2. Set default generation parameters")
        click.echo("  3. Set output directory")
        click.echo("  4. Show current configuration")
        click.echo("  5. Exit")

        choice = click.prompt(
            "Enter choice", type=click.Choice(["1", "2", "3", "4", "5"])
        )

        if choice == "1":
            _wizard_configure_engines(config_path, config, available_engines)
        elif choice == "2":
            _set_defaults(config_path, config)
        elif choice == "3":
            current_dir = config.get("output_dir", ".")
            new_dir = click.prompt(
                "Output directory",
                default=current_dir,
            )
            _set_output_dir(config_path, config, new_dir)
        elif choice == "4":
            _list_engines(config)
            click.echo("")
            click.echo("Generation defaults:")
            click.echo(f"  Width: {config.get('default_width', 1024)}")
            click.echo(f"  Height: {config.get('default_height', 1024)}")
            click.echo(f"  Guidance scale: {config.get('default_guidance_scale', 1.0)}")
            click.echo(f"  Steps: {config.get('default_num_inference_steps', 4)}")
            click.echo(f"  Format: {config.get('default_output_format', 'PNG')}")
            click.echo(f"  Output dir: {config.get('output_dir', '.')}")
        elif choice == "5":
            break

    click.echo("\nSetup complete. Use 'image setup --help' for more options.")


def _wizard_configure_engines(
    config_path: Path,
    config: dict,
    available_engines: list[str],
) -> None:
    """Interactive engine configuration."""
    engines = config.setdefault("engines", {})

    if engines:
        click.echo("\nConfigured engines:")
        for name in engines.keys():
            click.echo(f"  - {name}")
        if not click.confirm("\nAdd another engine?", default=False):
            return

    click.echo("\nAvailable engines:")
    for i, engine in enumerate(available_engines, 1):
        click.echo(f"  {i}. {engine}")
    click.echo(f"  {len(available_engines) + 1}. Back")

    choice = click.prompt("Enter choice", type=int)
    if choice == len(available_engines) + 1:
        return

    if 1 <= choice <= len(available_engines):
        engine_name = available_engines[choice - 1]
        _add_engine(config_path, config, engine_name)
