from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest

_MONITOR_STOP_FILE = Path("/tmp/fast-market-monitor.stop")


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("stop")
    def stop_cmd():
        """Abort the current monitor run immediately.

        Write a sentinel file that 'monitor run' checks when its alert_after
        threshold is exceeded. The running action is abandoned and the run exits.
        Run 'monitor wait' instead to extend the deadline.
        """
        _MONITOR_STOP_FILE.touch()
        click.echo("Sent: monitor run will stop at next check.")

    return CommandManifest(name="stop", click_command=stop_cmd)
