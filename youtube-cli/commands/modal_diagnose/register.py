from __future__ import annotations

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("modal-diagnose")
    def modal_diagnose_cmd():
        """Test Modal API connectivity and inspect the remote environment."""
        try:
            import modal
            from modal_client.app import app
            from modal_client.diagnose import run_diagnose
        except ImportError as e:
            raise click.ClickException(f"modal not installed: {e}")

        click.echo("Connecting to Modal...", err=True)
        with app.run():
            result = run_diagnose.remote()

        click.echo("Remote environment:")
        for key, value in result.items():
            click.echo(f"  {key}: {value}")

    return CommandManifest(name="modal-diagnose", click_command=modal_diagnose_cmd)
