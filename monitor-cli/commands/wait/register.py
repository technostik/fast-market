from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest

_MONITOR_WAIT_FILE = Path("/tmp/fast-market-monitor.wait")


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("wait")
    def wait_cmd():
        """Extend the current monitor run deadline by one increment.

        Write a sentinel file that 'monitor run' checks when its alert_after
        threshold is exceeded. Extends the deadline by the configured increment
        (default 5m). Run 'monitor stop' to abort instead.
        """
        _MONITOR_WAIT_FILE.touch()
        click.echo("Sent: monitor run deadline extended.")

    return CommandManifest(name="wait", click_command=wait_cmd)
