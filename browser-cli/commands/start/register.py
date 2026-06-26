from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import click
from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    is_cdp_available,
    read_browser_state,
    resolve_browser,
    detect_display,
    find_free_display,
    start_xvfb,
    start_xephyr,
    minimize_xephyr,
    stop_browser,
    write_browser_state,
)
from common.core.profile import resolve_profile

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("start")
    @click.option("--browser", "-b", default="google-chrome", show_default=True,
                  help="Browser binary to launch.")
    @click.option("--cdp-port", "-p", "cdp_port", type=int, default=9222, show_default=True,
                  help="Chrome DevTools Protocol port.")
    @click.option("--user-data-dir", "-u", default=None,
                  help="Chrome user data directory (defaults to the active profile's browser session dir).")
    @click.option("--extra-args", "-e", multiple=True, default=None,
                  help="Extra arguments to pass to the browser (can repeat).")
    @click.option("--silent", "-s", is_flag=True, default=False,
                  help="Start browser silently (suppress infobars, notifications, etc.).")
    @click.option("--hidden", is_flag=True, default=False,
                  help="Start browser minimized (window in taskbar, not stealing focus).")
    @click.option("--xvfb", is_flag=True, default=False,
                  help="Start browser on a virtual display (Xvfb) — fully invisible, no window on desktop.")
    def start_cmd(
        browser: str,
        cdp_port: int,
        user_data_dir: str | None,
        extra_args: tuple[str, ...] | None,
        silent: bool,
        hidden: bool,
        xvfb: bool,
    ) -> None:
        """Launch a Chromium browser with CDP enabled in the background."""
        ensure_agent_browser_installed()

        active_profile = resolve_profile()

        if is_cdp_available(cdp_port):
            state = read_browser_state()
            running_profile = state.get("profile")
            # Only auto-restart when the user relies on the active-profile session
            # (no explicit --user-data-dir) and the live browser was started for a
            # different profile. Browsers started before profiles were tracked have
            # no "profile" key, so they keep the old "already running" behaviour.
            if (
                user_data_dir is None
                and running_profile is not None
                and running_profile != active_profile
            ):
                click.echo(
                    f"Warning: browser on CDP port {cdp_port} belongs to profile "
                    f"'{running_profile}', but the active profile is "
                    f"'{active_profile}'. Restarting with '{active_profile}'...",
                    err=True,
                )
                stop_browser(cdp_port)
                xvfb_pid_old = state.get("xvfb_pid")
                if xvfb_pid_old:
                    try:
                        os.kill(xvfb_pid_old, 9)
                    except OSError:
                        pass
                # fall through and start a fresh browser for the active profile
            else:
                click.echo(f"Browser already running on CDP port {cdp_port}.", err=True)
                return

        browser = resolve_browser(browser)

        if user_data_dir is None:
            from common.core.paths import get_browser_user_data_dir

            user_data_dir = str(get_browser_user_data_dir())

        cmd = [
            browser,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--disable-features=OptimizationHints",
            "--remote-allow-origins=*",
        ]

        env = os.environ.copy()
        xvfb_pid: int | None = None
        xephyr_pid: int | None = None
        display: str | None = None
        real_display: str | None = None
        mode = "normal"

        if xvfb or hidden:
            # ── Virtual display mode ──────────────────────────────────────────
            real_display = os.environ.get("DISPLAY") or detect_display() or ":0"

            if hidden and not xvfb:
                # Reuse an existing Xephyr session when available so no new
                # window pops on screen (the previous one stays minimized).
                existing = read_browser_state()
                ex_pid = existing.get("xephyr_pid")
                ex_display = existing.get("display")
                if ex_pid and ex_display:
                    try:
                        os.kill(ex_pid, 0)  # Check alive
                        sock = f"/tmp/.X11-unix/X{ex_display.lstrip(':')}"
                        if Path(sock).exists():
                            click.echo(
                                f"Reusing existing Xephyr on {ex_display} (PID {ex_pid}).",
                                err=True,
                            )
                            xephyr_pid = ex_pid
                            display = ex_display
                            real_display = existing.get("real_display", real_display)
                            mode = "xephyr"
                    except (ProcessLookupError, OSError):
                        pass

                if xephyr_pid is None:
                    # No existing Xephyr — start a fresh one and minimize immediately
                    if shutil.which("Xephyr"):
                        display = find_free_display()
                        click.echo(f"Starting Xephyr on display {display}...", err=True)
                        xephyr_pid = start_xephyr(display)
                        if xephyr_pid is not None:
                            mode = "xephyr"
                            click.echo(f"Xephyr started (PID {xephyr_pid}) on {display}.", err=True)
                            minimize_xephyr(xephyr_pid, real_display)
                        else:
                            click.echo("Xephyr failed to start — falling back to Xvfb.", err=True)
                    else:
                        click.echo(
                            "Xephyr not found — falling back to Xvfb.\n"
                            "Install with: sudo apt install xserver-xephyr",
                            err=True,
                        )

            if xephyr_pid is None:
                # Xvfb: explicit --xvfb flag, or Xephyr unavailable/failed
                if display is None:
                    display = find_free_display()
                click.echo(f"Starting Xvfb on display {display}...", err=True)
                xvfb_pid = start_xvfb(display)
                mode = "xvfb"
                click.echo(f"Xvfb started (PID {xvfb_pid}) on {display}.", err=True)

            # Force X11: on Wayland Chrome uses WAYLAND_DISPLAY and ignores DISPLAY
            env.pop("WAYLAND_DISPLAY", None)
            env.pop("XDG_SESSION_TYPE", None)
            env["DISPLAY"] = display
            cmd.append("--ozone-platform=x11")

            # Always run silently on a virtual display — no infobars, no focus steal
            cmd += [
                "--disable-infobars",
                "--disable-notifications",
                "--disable-extensions",
                "--disable-default-apps",
                "--disable-background-networking",
                "--disable-sync",
                "--mute-audio",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-features=TranslateUI",
                "--noerrdialogs",
            ]

        else:
            # ── Real display mode ─────────────────────────────────────────────
            detected = detect_display()
            headless = detected is None

            if detected and not os.environ.get("DISPLAY"):
                click.echo(f"No $DISPLAY set — using detected display {detected}.", err=True)
                env["DISPLAY"] = detected

            if headless:
                click.echo(
                    "Warning: no display found — falling back to headless mode.\n"
                    "If you have a graphical session, set DISPLAY manually:\n"
                    "  export DISPLAY=:0   # replace :0 with your display number\n"
                    "  ls /tmp/.X11-unix/  # lists available displays",
                    err=True,
                )
                cmd += ["--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
                mode = "headless"

            elif silent:
                click.echo("Starting in silent mode.", err=True)
                mode = "normal"

            if silent and not headless:
                cmd += [
                    "--disable-infobars",
                    "--disable-notifications",
                    "--disable-extensions",
                    "--disable-default-apps",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--mute-audio",
                    "--autoplay-policy=no-user-gesture-required",
                ]

        if extra_args:
            cmd.extend(extra_args)

        stderr_log = tempfile.NamedTemporaryFile(mode="w", suffix="_browser_start.log", delete=False)
        stderr_log.close()

        click.echo(f"Starting {browser} on CDP port {cdp_port}...", err=True)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=open(stderr_log.name, "w"),
            start_new_session=True,
            env=env,
        )

        # Wait up to 15 s for CDP to become available
        for _ in range(30):
            if is_cdp_available(cdp_port):
                click.echo(f"Browser started successfully on CDP port {cdp_port}.", err=True)
                try:
                    os.unlink(stderr_log.name)
                except OSError:
                    pass
                write_browser_state({
                    "mode": mode,
                    "cdp_port": cdp_port,
                    "profile": active_profile,
                    "xvfb_pid": xvfb_pid,
                    "xephyr_pid": xephyr_pid,
                    "display": display,
                    "real_display": real_display,
                })
                return
            time.sleep(0.5)

        # ── Startup failed ────────────────────────────────────────────────────
        exit_code = proc.poll()
        if exit_code is not None:
            click.echo(f"Browser process exited immediately (exit code {exit_code}).", err=True)
        else:
            click.echo(
                f"CDP port {cdp_port} never became available after 15 s "
                f"(process still running as PID {proc.pid}).",
                err=True,
            )

        try:
            with open(stderr_log.name) as f:
                stderr_text = f.read(3000).strip()
            if stderr_text:
                click.echo(f"\nChromium output:\n{stderr_text}\n", err=True)
        except OSError:
            pass
        finally:
            try:
                os.unlink(stderr_log.name)
            except OSError:
                pass

        if xvfb_pid:
            try:
                os.kill(xvfb_pid, 9)
            except OSError:
                pass
        if xephyr_pid:
            try:
                os.kill(xephyr_pid, 9)
            except OSError:
                pass

    return CommandManifest(name="start", click_command=start_cmd)
