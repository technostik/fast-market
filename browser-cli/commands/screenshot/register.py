from __future__ import annotations

import click
from commands.base import CommandManifest
from commands.helpers import take_cdp_screenshot


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("screenshot")
    @click.option("--cdp-port", "-p", "cdp_port", type=int, default=9222, show_default=True,
                  help="Chrome DevTools Protocol port.")
    @click.option("--output", "-o", default="/tmp/browser_screenshot.png", show_default=True,
                  help="Output file path for the screenshot.")
    @click.option("--open", "open_after", is_flag=True, default=False,
                  help="Open the screenshot with xdg-open after saving.")
    def screenshot_cmd(cdp_port: int, output: str, open_after: bool) -> None:
        """Take a screenshot of the current browser tab via CDP."""
        try:
            take_cdp_screenshot(cdp_port, output)
        except Exception as e:
            raise click.ClickException(f"Screenshot failed: {e}")

        click.echo(output)

        if open_after:
            import subprocess
            subprocess.Popen(["xdg-open", output])

    return CommandManifest(name="screenshot", click_command=screenshot_cmd)
