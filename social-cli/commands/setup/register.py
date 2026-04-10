"""Setup command — manage backend configurations.

Subcommands:
    social setup show --backend=twitter   # Show config for one backend
    social setup show                     # Show all merged configs
    social setup edit --backend=twitter   # Edit one backend's config
    social setup edit                     # Edit all merged configs (nested YAML)
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.completion import BackendParamType
from commands.helpers import out
from common.cli.helpers import get_editor, open_editor
from common.core.yaml_utils import dump_yaml

# Re-import config functions
from core.config import (
    _social_config_root,
    ConfigError,
    _deep_merge,
)


def _backend_config_path(backend: str) -> Path:
    """Return the path to ~/.config/social/<backend>/config.yaml."""
    return _social_config_root() / backend / "config.yaml"


def _write_yaml_file(path: Path, content: str) -> None:
    """Ensure parent dirs exist and write YAML content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _read_backend_config(backend: str) -> dict | None:
    """Read a single backend's config, or None if it doesn't exist."""
    cfg_path = _backend_config_path(backend)
    if not cfg_path.exists():
        return None
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


def _read_all_backend_configs(plugin_manifests: dict) -> dict:
    """Read all backends into a nested dict: {backend_name: {config}}."""
    result = {}
    for name in sorted(plugin_manifests.keys()):
        data = _read_backend_config(name)
        if data:
            result[name] = data
    return result


def _write_merged_config(merged: dict, plugin_manifests: dict) -> dict:
    """Write a merged nested config dict back to individual backend files.

    Returns dict of {backend: status}.
    """
    statuses = {}
    for backend, data in merged.items():
        if backend not in plugin_manifests:
            statuses[backend] = f"skipped (unknown backend: {backend})"
            continue
        cfg_path = _backend_config_path(backend)
        _write_yaml_file(cfg_path, dump_yaml(data, sort_keys=False))
        statuses[backend] = f"written to {cfg_path}"
    return statuses


# ---------------------------------------------------------------------------
# Setup group
# ---------------------------------------------------------------------------
@click.group("setup")
def setup_group():
    """Manage backend configurations."""
    pass


# ---------------------------------------------------------------------------
# setup show
# ---------------------------------------------------------------------------
@setup_group.command("show")
@click.option(
    "--backend",
    "-b",
    "backend",
    type=BackendParamType(),
    default=None,
    help="Backend to show config for (shows all if omitted).",
)
@click.option(
    "--format",
    "-F",
    "fmt",
    type=click.Choice(["json", "text", "yaml"]),
    default="yaml",
    help="Output format.",
)
@click.pass_context
def setup_show(ctx, backend, fmt):
    """Show configuration for a backend or all backends."""
    # Discover plugins to get backend names
    from cli.main import _plugin_manifests

    if not _plugin_manifests:
        raise click.ClickException("No plugins discovered. Check your config.")

    if backend:
        data = _read_backend_config(backend)
        if data is None:
            out({"backend": backend, "status": "not_found", "path": str(_backend_config_path(backend))}, fmt)
        else:
            out({"backend": backend, **data}, fmt)
    else:
        # Show all merged
        all_configs = _read_all_backend_configs(_plugin_manifests)
        if not all_configs:
            click.echo("No backend configurations found.", err=True)
            click.echo("Use 'social setup edit --backend=<name>' to create one.", err=True)
        else:
            if fmt == "yaml":
                click.echo(dump_yaml(all_configs, sort_keys=False))
            else:
                out(all_configs, fmt)


# ---------------------------------------------------------------------------
# setup edit
# ---------------------------------------------------------------------------
@setup_group.command("edit")
@click.option(
    "--backend",
    "-b",
    "backend",
    type=BackendParamType(),
    default=None,
    help="Backend to edit (edits all merged if omitted).",
)
@click.pass_context
def setup_edit(ctx, backend):
    """Edit configuration for a backend or all backends."""
    from cli.main import _plugin_manifests

    if not _plugin_manifests:
        raise click.ClickException("No plugins discovered. Check your config.")

    if backend:
        _edit_single_backend(backend, _plugin_manifests)
    else:
        _edit_all_backends(_plugin_manifests)


def _edit_single_backend(backend: str, plugin_manifests: dict) -> None:
    """Edit a single backend's config file."""
    cfg_path = _backend_config_path(backend)

    # If config doesn't exist, create from plugin template
    if not cfg_path.exists():
        manifest = plugin_manifests.get(backend)
        if manifest and manifest.config_template:
            click.echo(f"Creating default config for '{backend}' at {cfg_path}")
            _write_yaml_file(cfg_path, manifest.config_template)
        else:
            raise click.ClickException(
                f"No config file found for '{backend}' and no default template available.\n"
                f"Create: {cfg_path}"
            )

    click.echo(f"Editing: {cfg_path}")
    open_editor(cfg_path)


def _edit_all_backends(plugin_manifests: dict) -> None:
    """Edit all backends as one merged nested YAML file."""
    # Read current configs
    merged = _read_all_backend_configs(plugin_manifests)

    # Fill in missing backends from templates
    for name, manifest in plugin_manifests.items():
        if name not in merged and manifest.config_template:
            # Parse the template as a placeholder (we don't write it yet)
            try:
                template_data = yaml.safe_load(manifest.config_template) or {}
                merged[name] = template_data
            except yaml.YAMLError:
                merged[name] = {}

    if not merged:
        click.echo("No backends found to edit.", err=True)
        return

    # Build the nested YAML content
    original_content = dump_yaml(merged, sort_keys=False)

    # Write to a temp file for editing
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="social-setup-", delete=False
    ) as tmp:
        tmp.write(original_content)
        tmp_path = tmp.name

    try:
        # Open in editor
        editor = get_editor()
        click.echo(f"Editing all backends merged config in {editor}...")
        subprocess.run([editor, tmp_path], check=True)

        # Read the edited content
        with open(tmp_path) as f:
            edited_content = f.read()
            edited_data = yaml.safe_load(edited_content) or {}

        # Validate it's still a dict
        if not isinstance(edited_data, dict):
            raise click.ClickException("Edited config is not a valid YAML mapping.")

        # Split and write back
        statuses = _write_merged_config(edited_data, plugin_manifests)

        click.echo("Configurations updated:")
        for b, status in statuses.items():
            click.echo(f"  {b}: {status}")

    except subprocess.CalledProcessError as e:
        click.echo(f"Editor exited with error: {e}", err=True)
    except yaml.YAMLError as e:
        raise click.ClickException(f"Invalid YAML after editing: {e}")
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register(plugin_manifests: dict) -> CommandManifest:
    return CommandManifest(
        name="setup",
        click_command=setup_group,
    )
