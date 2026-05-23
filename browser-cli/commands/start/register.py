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
    write_browser_state,
)

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
    if shutil.which(requested):
        return requested
    if requested not in _BROWSER_CANDIDATES:
        raise click.ClickException(
            f"Browser binary not found: '{requested}'\n" + _INSTALL_HINT
        )
    for candidate in _BROWSER_CANDIDATES:
        if shutil.which(candidate):
            click.echo(f"'{requested}' not found — using '{candidate}' instead.", err=True)
            return candidate
    raise click.ClickException(_INSTALL_HINT)


def _detect_display() -> str | None:
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
                        kv.split(b"=", 1) for kv in f.read().split(b"\0") if b"=" in kv
                    )
                if b"DISPLAY" in env:
                    return env[b"DISPLAY"].decode()
            except OSError:
                continue
    except OSError:
        pass
    return None


def _find_free_display() -> str:
    for n in range(99, 200):
        if not Path(f"/tmp/.X{n}-lock").exists():
            return f":{n}"
    raise click.ClickException("No free X display numbers available (checked :99–:199)")


def _start_xvfb(display: str) -> int:
    """Start Xvfb on the given display. Returns its PID."""
    if not shutil.which("Xvfb"):
        raise click.ClickException(
            "Xvfb not found. Install it with:\n  sudo apt install xvfb"
        )
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    if proc.poll() is not None:
        raise click.ClickException(f"Xvfb failed to start on display {display}")
    return proc.pid


def _start_xephyr(display: str, width: int = 1920, height: int = 1080) -> int | None:
    """Start Xephyr on the given display. Returns its PID, or None on failure."""
    proc = subprocess.Popen(
        ["Xephyr", display, "-screen", f"{width}x{height}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    if proc.poll() is not None:
        return None
    return proc.pid


def _minimize_xephyr(xephyr_pid: int, real_display: str) -> None:
    """Minimize the Xephyr window so it starts tucked in the taskbar."""
    if not shutil.which("xdotool"):
        return
    env = {**os.environ, "DISPLAY": real_display}
    for _ in range(10):
        result = subprocess.run(
            ["xdotool", "search", "--pid", str(xephyr_pid)],
            capture_output=True, text=True, env=env,
        )
        ids = result.stdout.strip().split()
        if ids:
            subprocess.run(["xdotool", "windowminimize", ids[-1]], env=env, check=False)
            return
        time.sleep(0.3)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("start")
    @click.option("--browser", "-b", default="google-chrome", show_default=True,
                  help="Browser binary to launch.")
    @click.option("--cdp-port", "-p", "cdp_port", type=int, default=9222, show_default=True,
                  help="Chrome DevTools Protocol port.")
    @click.option("--user-data-dir", "-u", default=None,
                  help="Chrome user data directory (defaults to ~/.chrome-debug-profile).")
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

        if is_cdp_available(cdp_port):
            click.echo(f"Browser already running on CDP port {cdp_port}.", err=True)
            return

        browser = _resolve_browser(browser)

        if user_data_dir is None:
            user_data_dir = str(Path.home() / ".chrome-debug-profile")

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
            real_display = os.environ.get("DISPLAY") or _detect_display() or ":0"

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
                        display = _find_free_display()
                        click.echo(f"Starting Xephyr on display {display}...", err=True)
                        xephyr_pid = _start_xephyr(display)
                        if xephyr_pid is not None:
                            mode = "xephyr"
                            click.echo(f"Xephyr started (PID {xephyr_pid}) on {display}.", err=True)
                            _minimize_xephyr(xephyr_pid, real_display)
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
                    display = _find_free_display()
                click.echo(f"Starting Xvfb on display {display}...", err=True)
                xvfb_pid = _start_xvfb(display)
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
            detected = _detect_display()
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
