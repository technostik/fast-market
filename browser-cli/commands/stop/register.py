from __future__ import annotations

import signal
import subprocess

import click
from commands.base import CommandManifest
from commands.helpers import is_cdp_available, read_browser_state, write_browser_state, clear_browser_state


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("stop")
    @click.option(
        "--cdp-port",
        "-p",
        "cdp_port",
        type=int,
        default=9222,
        show_default=True,
        help="Chrome DevTools Protocol port of the browser to stop.",
    )
    def stop_cmd(cdp_port: int) -> None:
        """Stop the Chromium browser running on the given CDP port."""
        if not is_cdp_available(cdp_port):
            click.echo(f"No browser found on CDP port {cdp_port}.", err=True)
            return

        state = read_browser_state()

        # Find the chrome process listening on the CDP port
        try:
            # Use lsof to find the process
            result = subprocess.run(
                ["lsof", "-ti", f":{cdp_port}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    pid = pid.strip()
                    try:
                        os_kill(int(pid))
                        click.echo(f"Stopped browser process (PID {pid}).", err=True)
                    except ProcessLookupError:
                        pass
            else:
                # Fallback: find chrome processes with the cdp port in args
                result = subprocess.run(
                    ["pgrep", "-f", "--", f"--remote-debugging-port={cdp_port}"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and result.stdout.strip():
                    pids = result.stdout.strip().split("\n")
                    for pid in pids:
                        pid = pid.strip()
                        try:
                            os_kill(int(pid))
                            click.echo(f"Stopped browser process (PID {pid}).", err=True)
                        except ProcessLookupError:
                            pass
                else:
                    click.echo(
                        f"Could not find browser process on CDP port {cdp_port}. "
                        f"You may need to close it manually.",
                        err=True,
                    )
        except FileNotFoundError:
            click.echo(
                "Neither 'lsof' nor 'pgrep' found. Cannot stop browser automatically. "
                "Please close it manually.",
                err=True,
            )

        xvfb_pid = state.get("xvfb_pid")
        if xvfb_pid:
            try:
                os_kill(xvfb_pid)
                click.echo(f"Stopped Xvfb (PID {xvfb_pid}).", err=True)
            except (ProcessLookupError, OSError):
                pass

        xephyr_pid = state.get("xephyr_pid")
        if xephyr_pid:
            # Keep Xephyr alive so the next "browser start --hidden" reuses it
            # without popping a new window on screen.
            import os as _os
            try:
                _os.kill(xephyr_pid, 0)  # Check it's still alive
                write_browser_state({
                    "mode": "xephyr",
                    "xephyr_pid": xephyr_pid,
                    "display": state.get("display"),
                    "real_display": state.get("real_display"),
                })
                click.echo("Xephyr kept running for next session.", err=True)
                return
            except (ProcessLookupError, OSError):
                pass  # Xephyr already dead — fall through and clear state

        clear_browser_state()

    return CommandManifest(
        name="stop",
        click_command=stop_cmd,
    )


def os_kill(pid: int) -> None:
    """Send SIGTERM then SIGKILL if needed."""
    import os
    import time

    os.kill(pid, signal.SIGTERM)
    # Give it a moment to shut down gracefully
    time.sleep(0.5)
    # Force kill if still alive
    try:
        os.kill(pid, 0)  # Check if process exists
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
