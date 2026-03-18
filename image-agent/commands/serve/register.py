from __future__ import annotations

from pathlib import Path

import click

from api.server import run_server
from commands.base import CommandManifest

_TOOL_ROOT = Path(__file__).resolve().parents[2]


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("serve")
    @click.option("--host", default="127.0.0.1", help="Host to bind to")
    @click.option("--port", type=int, default=8000, help="Port to bind to")
    @click.pass_context
    def serve_cmd(ctx, host, port):
        """Start the image-agent API server."""
        click.echo(f"Starting image-agent API server on {host}:{port}")
        click.echo("Press Ctrl+C to stop")

        try:
            run_server(host, port, tool_root=_TOOL_ROOT)
        except KeyboardInterrupt:
            click.echo("\nServer stopped")

    return CommandManifest(name="serve", click_command=serve_cmd)
