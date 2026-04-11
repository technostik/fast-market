from __future__ import annotations

import subprocess

import click
from commands.base import CommandManifest
from commands.helpers import ensure_agent_browser_installed, is_cdp_available


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("start")
    @click.option(
        "--browser",
        "-b",
        default="google-chrome",
        show_default=True,
        help="Browser binary to launch.",
    )
    @click.option(
        "--cdp-port",
        "-p",
        "cdp_port",
        type=int,
        default=9222,
        show_default=True,
        help="Chrome DevTools Protocol port.",
    )
    @click.option(
        "--user-data-dir",
        "-u",
        default=None,
        help="Chrome user data directory (defaults to ~/.chrome-debug-profile).",
    )
    @click.option(
        "--extra-args",
        "-e",
        multiple=True,
        default=None,
        help="Extra arguments to pass to the browser (can repeat).",
    )
    def start_cmd(browser: str, cdp_port: int, user_data_dir: str | None, extra_args: tuple[str, ...] | None) -> None:
        """Launch a Chromium browser with CDP enabled in the background."""
        ensure_agent_browser_installed()

        if is_cdp_available(cdp_port):
            click.echo(f"Browser already running on CDP port {cdp_port}.", err=True)
            return

        import os
        from pathlib import Path

        if user_data_dir is None:
            user_data_dir = str(Path.home() / ".chrome-debug-profile")

        cmd = [
            browser,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--disable-features=OptimizationHints",
        ]

        if extra_args:
            cmd.extend(extra_args)

        click.echo(f"Starting {browser} on CDP port {cdp_port}...", err=True)
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait briefly for the port to become available
        import time
        for _ in range(30):
            if is_cdp_available(cdp_port):
                click.echo(f"Browser started successfully on CDP port {cdp_port}.", err=True)
                return
            time.sleep(0.5)

        click.echo(
            f"Warning: Browser may not have started on port {cdp_port}. "
            f"Check that '{browser}' is installed and accessible.",
            err=True,
        )

    return CommandManifest(
        name="start",
        click_command=start_cmd,
    )
