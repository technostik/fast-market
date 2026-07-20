from __future__ import annotations

import json

import click

from commands.helpers import _configure_logging
from commands.setup.helpers import (
    add_engine,
    get_config_path,
    load_config,
    remove_engine,
    set_default_engine,
    set_model_path,
)


def register(plugin_manifests: dict) -> click.Command:
    group = click.Group(
        "engine", help="Manage image generation engines."
    )

    @group.command("list", help="List available image generation engines.")
    @click.option(
        "--format",
        "-f",
        "output_format",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format.",
    )
    @click.pass_context
    def list_cmd(ctx, output_format, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config = load_config(get_config_path())
        # All engines the system can discover (plugins), regardless of whether
        # they are configured in the config file.
        available = sorted(plugin_manifests.keys()) if plugin_manifests else []
        configured = set((config.get("engines") or {}).keys())
        default_engine = config.get("default_engine", "")
        if output_format == "json":
            click.echo(json.dumps({
                "engines": available,
                "configured": sorted(configured),
                "default": default_engine,
            }))
            return
        if not available:
            click.echo("No engines available.")
            return
        click.echo("Available engines:")
        for name in available:
            marks = []
            if name == default_engine:
                marks.append("default")
            if name in configured:
                marks.append("configured")
            suffix = f" ({', '.join(marks)})" if marks else ""
            click.echo(f"  - {name}{suffix}")

    @group.command("add", help="Add an engine (flux2).")
    @click.option(
        "--engine",
        "-e",
        type=click.Choice(["flux2"]),
        required=True,
        help="Engine to add",
    )
    @click.pass_context
    def add_cmd(ctx, engine, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        add_engine(config_path, load_config(config_path), engine)

    @group.command("remove", help="Remove an engine.")
    @click.argument("engine")
    @click.pass_context
    def remove_cmd(ctx, engine, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        remove_engine(config_path, load_config(config_path), engine)

    @group.command("set-default", help="Set the default engine.")
    @click.argument("engine")
    @click.pass_context
    def set_default_cmd(ctx, engine, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        set_default_engine(config_path, load_config(config_path), engine)

    @group.command("set-model-path", help="Set model path (format: engine:path).")
    @click.argument("engine_path")
    @click.pass_context
    def set_model_path_cmd(ctx, engine_path, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        set_model_path(config_path, load_config(config_path), engine_path)

    return group
