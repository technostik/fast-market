from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

import click
from commands.base import CommandManifest
from commands.helpers import ensure_agent_browser_installed, is_cdp_available

# Candidates tried in order when the requested binary is not found
_BROWSER_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chromium-bsu",
]

_INSTALL_HINT = (
    "No Chromium-based browser binary was found.\n"
    "On Ubuntu/Debian, install Chromium with:\n"
    "  sudo apt install chromium\n"
    "Or point to an existing binary with:\n"
    "  browser start --browser /path/to/chromium"
)


def _resolve_browser(requested: str) -> str:
    """Return the resolved binary path, auto-detecting if the requested one is missing."""
    if shutil.which(requested):
        return requested

    # Explicit non-default path that wasn't found — fail immediately with a clear message
    if requested not in _BROWSER_CANDIDATES:
        raise click.ClickException(
            f"Browser binary not found: '{requested}'\n" + _INSTALL_HINT
        )

    # Default / well-known name — try the full candidate list
    for candidate in _BROWSER_CANDIDATES:
        if shutil.which(candidate):
            click.echo(
                f"'{requested}' not found — using '{candidate}' instead.", err=True
            )
            return candidate

    raise click.ClickException(_INSTALL_HINT)


def _detect_display() -> str | None:
    """
    Return a usable DISPLAY value for the current user, or None.
    Priority:
      1. $DISPLAY / $WAYLAND_DISPLAY already set in the environment
      2. Scan /proc for a process owned by this user that has DISPLAY set
    """
    if os.environ.get("DISPLAY"):
        return os.environ["DISPLAY"]
    if os.environ.get("WAYLAND_DISPLAY"):
        return os.environ["WAYLAND_DISPLAY"]

    uid = os.getuid()
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid != uid:
                    continue
                with open(f"/proc/{entry.name}/environ", "rb") as f:
                    env = dict(
                        kv.split(b"=", 1) for kv in f.read().split(b"\0")
                        if b"=" in kv
                    )
                if b"DISPLAY" in env:
                    return env[b"DISPLAY"].decode()
            except OSError:
                continue
    except OSError:
        pass

    return None


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
    @click.option(
        "--silent",
        "-s",
        is_flag=True,
        default=False,
        help="Start browser silently (suppress logs, infobars, first-run, etc.) without using headless mode.",
    )
    def start_cmd(browser: str, cdp_port: int, user_data_dir: str | None, extra_args: tuple[str, ...] | None, silent: bool) -> None:
        """Launch a Chromium browser with CDP enabled in the background."""
        ensure_agent_browser_installed()

        if is_cdp_available(cdp_port):
            click.echo(f"Browser already running on CDP port {cdp_port}.", err=True)
            return

        from pathlib import Path

        browser = _resolve_browser(browser)

        if user_data_dir is None:
            user_data_dir = str(Path.home() / ".chrome-debug-profile")

        cmd = [
            browser,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--disable-features=OptimizationHints",
        ]

        # Auto-detect display; fall back to headless only if none found
        display = _detect_display()
        headless = display is None
        if display and not os.environ.get("DISPLAY"):
            click.echo(f"No $DISPLAY set — using detected display {display}.", err=True)
            os.environ["DISPLAY"] = display

        if headless:
            click.echo(
                "Warning: no display found — falling back to headless mode.\n"
                "If you have a graphical session running, set DISPLAY manually:\n"
                "  export DISPLAY=:0   # replace :0 with your display number\n"
                "  ls /tmp/.X11-unix/  # lists available displays",
                err=True,
            )
            cmd += [
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        elif silent:
            # Silent but visible mode
            click.echo("Starting in silent (non-headless) mode.", err=True)
            cmd += [
                "--disable-infobars",
                "--disable-notifications",
                "--disable-extensions",
                "--disable-default-apps",
                "--no-first-run",
                "--disable-background-networking",
                "--disable-sync",
                "--mute-audio",
                "--autoplay-policy=no-user-gesture-required",
            ]

        if extra_args:
            cmd.extend(extra_args)

        # Capture stderr to a temp file so we can surface errors if startup fails
        stderr_log = tempfile.NamedTemporaryFile(
            mode="w", suffix="_browser_start.log", delete=False
        )
        stderr_log.close()

        click.echo(f"Starting {browser} on CDP port {cdp_port}...", err=True)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=open(stderr_log.name, "w"),
            start_new_session=True,
        )

        # Wait up to 15 s for CDP to become available
        for _ in range(30):
            if is_cdp_available(cdp_port):
                click.echo(
                    f"Browser started successfully on CDP port {cdp_port}.", err=True
                )
                try:
                    os.unlink(stderr_log.name)
                except OSError:
                    pass
                return
            time.sleep(0.5)

        # ── Startup failed — give the user something actionable ────────────────

        # Did the process exit already?
        exit_code = proc.poll()
        if exit_code is not None:
            click.echo(f"Browser process exited immediately (exit code {exit_code}).", err=True)
        else:
            click.echo(
                f"CDP port {cdp_port} never became available after 15 s "
                f"(process is still running as PID {proc.pid}).",
                err=True,
            )

        # Surface whatever Chromium printed to stderr
        try:
            with open(stderr_log.name) as f:
                stderr_text = f.read(3000).strip()
            if stderr_text:
                click.echo(f"\nChromium output:\n{stderr_text}\n", err=True)
        except OSError:
            stderr_text = ""
        finally:
            try:
                os.unlink(stderr_log.name)
            except OSError:
                pass

        # Targeted hints based on what we know
        hints = []
        if not headless:
            hints.append(
                "You appear to have a display, but Chromium failed to open it.\n"
                "If you are over SSH, re-connect with X11 forwarding:\n"
                "  ssh -X user@host\n"
                "Or force headless mode:\n"
                "  browser start -e --headless=new -e --disable-gpu -e --no-sandbox"
            )
        else:
            hints.append(
                "Headless flags were added automatically, but Chromium still failed.\n"
                "Common fixes:\n"
                "  • Snap Chromium sometimes needs a real session — try the .deb version:\n"
                "      sudo snap remove chromium\n"
                "      sudo apt install -y chromium-browser   # or chromium\n"
                "  • Missing shared libs / sandbox:\n"
                "      browser start -e --headless=new -e --disable-gpu -e --no-sandbox -e --disable-dev-shm-usage\n"
                "  • Check the Chromium output above for the specific error."
            )

        click.echo("\n".join(hints), err=True)

    return CommandManifest(
        name="start",
        click_command=start_cmd,
    )
