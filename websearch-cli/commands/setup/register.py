from __future__ import annotations

import importlib
from pathlib import Path

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    subcommands_dir = Path(__file__).parent / "subcommands"
    group = click.Group(
        "setup", help="Configure websearch defaults (language, limit, per-plugin keys)."
    )

    if subcommands_dir.exists():
        for entry in sorted(subcommands_dir.iterdir()):
            if entry.suffix == ".py" and entry.stem != "__init__":
                mod = importlib.import_module(f"commands.setup.subcommands.{entry.stem}")
                if hasattr(mod, "register"):
                    group.add_command(mod.register(plugin_manifests))

    return CommandManifest(name="setup", click_command=group)
