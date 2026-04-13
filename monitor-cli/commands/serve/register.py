from __future__ import annotations

import warnings

import click

from commands.base import CommandManifest
from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command(
        "serve",
        help="Start the HTTP API server and web interface for viewing logs and status.",
    )
    @click.option("--port", "-p", type=int, default=8006)
    @click.pass_context
    def serve_cmd(ctx, port, **kwargs):
        warnings.warn(
            "monitor serve is deprecated. Use 'webux serve' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        click.echo("⚠️  monitor serve is deprecated. Use 'webux serve' instead.", err=True)
        import uvicorn

        _configure_logging(ctx.obj["verbose"])
        uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)

    return CommandManifest(name="serve", click_command=serve_cmd)
