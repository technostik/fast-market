from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import click

from common.cli.helpers import out as _out

_AGENT_BROWSER = "agent-browser"

TIMEOUT_RE = re.compile(r"timed?\s*out|timeout", re.IGNORECASE)


def read_clipboard() -> str:
    """Read the current clipboard text using the best available tool."""
    for cmd in [
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["wl-paste", "--no-newline"],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                return r.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise click.ClickException(
        "Could not read clipboard: install xclip, xsel, or wl-paste."
    )

_TOOL_ROOT = Path(__file__).resolve().parents[1]
_STATE_FILE = Path("/tmp/fast-market-browser.json")


def read_browser_state() -> dict:
    """Return the persisted browser state (mode, xvfb_pid, display, cdp_port)."""
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def write_browser_state(state: dict) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def clear_browser_state() -> None:
    try:
        _STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def take_cdp_screenshot(cdp_port: int, output_path: str) -> str:
    """Take a CDP screenshot of the first tab. Returns output_path."""
    import base64
    import urllib.request
    import websocket

    with urllib.request.urlopen(f"http://localhost:{cdp_port}/json") as resp:
        tabs = json.loads(resp.read())
    if not tabs:
        raise RuntimeError("No browser tabs found")

    ws_url = tabs[0]["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=10)
    ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
    result = json.loads(ws.recv())
    ws.close()

    data = result.get("result", {}).get("data", "")
    if not data:
        raise RuntimeError("Empty screenshot data returned from CDP")

    Path(output_path).write_bytes(base64.b64decode(data))
    return output_path


def out(data: object, fmt: str) -> None:
    """Standard output formatting."""
    _out(data, fmt)


def ensure_agent_browser_installed() -> None:
    """Check that agent-browser is on PATH, error with install hint if missing."""
    import shutil

    if shutil.which(_AGENT_BROWSER) is None:
        raise click.ClickException(
            f"'{_AGENT_BROWSER}' not found on PATH. Install it with: npm install -g {_AGENT_BROWSER}"
        )


def substitute_params(instruction: str, params: dict[str, str]) -> str:
    """Replace {key} placeholders in the instruction with param values."""
    def _replacer(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            raise click.ClickException(
                f"Parameter '{key}' used in instruction but not provided. "
                f"Available: {list(params.keys())}"
            )
        return params[key]

    return re.sub(r"\{(\w+)\}", _replacer, instruction)


def build_agent_cmd(
    instruction: str,
    cdp_port: int = 9222,
    timeout: int | None = None,
) -> list[str]:
    """Build the agent-browser command line."""
    try:
        args = shlex.split(instruction)
    except ValueError:
        # Fall back: pass instruction as a single argument if quoting is unbalanced
        args = [instruction]
    cmd = [
        _AGENT_BROWSER,
        "--cdp",
        str(cdp_port),
        *args,
    ]
    return cmd


def run_agent_cmd(
    instruction: str,
    cdp_port: int = 9222,
    timeout: int | None = None,
    capture_stderr: bool = True,
) -> subprocess.CompletedProcess:
    """Run an agent-browser instruction and return the result."""
    cmd = build_agent_cmd(instruction, cdp_port, timeout)
    timeout_seconds = timeout / 1000 if timeout else None
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def launch_browser(cdp_port: int, user_data_dir: str | None = None) -> None:
    """Launch Chromium with CDP enabled in the background and wait until ready."""
    if user_data_dir is None:
        from common.core.paths import get_browser_user_data_dir

        user_data_dir = str(get_browser_user_data_dir())

    subprocess.Popen(
        [
            "google-chrome",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--disable-features=OptimizationHints",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    click.echo(f"Launching browser on CDP port {cdp_port}...", err=True)
    for _ in range(30):
        if is_cdp_available(cdp_port):
            return
        time.sleep(0.5)
    click.echo(f"Warning: Browser may not have started on port {cdp_port}.", err=True)


def stop_browser(cdp_port: int) -> None:
    """Stop the browser process listening on the given CDP port."""
    import os
    import signal

    pids: list[int] = []
    for finder in [
        ["lsof", "-ti", f"TCP:*:{cdp_port}"],
        ["pgrep", "-f", f"--remote-debugging-port={cdp_port}"],
    ]:
        try:
            r = subprocess.run(finder, capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                pids = [int(p) for p in r.stdout.strip().split("\n")]
                break
        except (FileNotFoundError, ValueError):
            pass

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(0.5)
    for pid in pids:
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_instructions(
    instructions: list[str],
    cdp_port: int,
    timeout: int | None,
    fmt: str,
) -> tuple[list[dict], list[dict]]:
    """Execute a list of agent-browser instructions. Returns (results, errors)."""
    results: list[dict] = []
    errors: list[dict] = []

    for i, instruction in enumerate(instructions):
        if fmt == "text":
            click.echo(f"  [{i + 1}/{len(instructions)}] {instruction}", err=True)

        inst_timeout = None if instruction.startswith("upload ") else timeout
        entry: dict = {}

        if inst_timeout is not None:
            start_ms = time.monotonic() * 1000
            attempt = 0
            while True:
                attempt += 1
                try:
                    result = run_agent_cmd(instruction, cdp_port, timeout=inst_timeout)
                except Exception as exc:
                    entry = {
                        "instruction": instruction,
                        "stdout": "",
                        "stderr": str(exc),
                        "exit_code": 1,
                        "success": False,
                        "attempts": attempt,
                    }
                    if TIMEOUT_RE.search(str(exc)):
                        elapsed_ms = (time.monotonic() * 1000) - start_ms
                        remaining_ms = inst_timeout - elapsed_ms
                        if remaining_ms > 0 and attempt < 50:
                            if fmt == "text":
                                click.echo(
                                    f"    Timeout — retrying (attempt {attempt}, "
                                    f"{remaining_ms:.0f}ms left)…",
                                    err=True,
                                )
                            continue
                    if fmt == "text":
                        click.echo(f"    Error: {exc}", err=True)
                    break
                else:
                    entry = {
                        "instruction": instruction,
                        "stdout": result.stdout.strip(),
                        "stderr": result.stderr.strip(),
                        "exit_code": result.returncode,
                        "success": result.returncode == 0,
                        "attempts": attempt,
                    }
                    if result.returncode != 0 and TIMEOUT_RE.search(result.stderr):
                        elapsed_ms = (time.monotonic() * 1000) - start_ms
                        remaining_ms = inst_timeout - elapsed_ms
                        if remaining_ms > 0 and attempt < 50:
                            if fmt == "text":
                                click.echo(
                                    f"    Timeout — retrying (attempt {attempt}, "
                                    f"{remaining_ms:.0f}ms left)…",
                                    err=True,
                                )
                            continue
                    if fmt == "text" and entry["success"] and entry["stdout"]:
                        click.echo(entry["stdout"])
                    break
        else:
            try:
                result = run_agent_cmd(instruction, cdp_port, timeout=None)
            except Exception as exc:
                entry = {
                    "instruction": instruction,
                    "stdout": "",
                    "stderr": str(exc),
                    "exit_code": 1,
                    "success": False,
                }
                if fmt == "text":
                    click.echo(f"    Error: {exc}", err=True)
            else:
                entry = {
                    "instruction": instruction,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "exit_code": result.returncode,
                    "success": result.returncode == 0,
                }
                if fmt == "text" and entry["success"] and entry["stdout"]:
                    click.echo(entry["stdout"])

        results.append(entry)
        if entry.get("exit_code", 1) != 0:
            errors.append(entry)
            if fmt == "text" and entry.get("stderr"):
                click.echo(f"    Error: {entry['stderr']}", err=True)

    return results, errors


def read_stdin() -> str:
    """Read content from stdin, error if empty or tty."""
    if sys.stdin.isatty():
        raise click.ClickException(
            "No stdin available (pipe content into this command)"
        )
    content = sys.stdin.read().strip()
    if not content:
        raise click.ClickException("No input from stdin")
    return content


def is_cdp_available(cdp_port: int = 9222) -> bool:
    """Check if a browser with CDP is listening on the given port."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex(("127.0.0.1", cdp_port))
        return result == 0
    finally:
        sock.close()


# ── Browser resolution ────────────────────────────────────────────────────

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


def resolve_browser(requested: str) -> str:
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


# ── Display helpers ───────────────────────────────────────────────────────

def detect_display() -> str | None:
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


def find_free_display() -> str:
    for n in range(99, 200):
        if not Path(f"/tmp/.X{n}-lock").exists():
            return f":{n}"
    raise click.ClickException("No free X display numbers available (checked :99–:199)")


def start_xvfb(display: str) -> int:
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


def start_xephyr(display: str, width: int = 1920, height: int = 1080) -> int | None:
    """Start Xephyr on the given display. Returns its PID, or None on failure."""
    log = tempfile.NamedTemporaryFile(mode="w", suffix="_xephyr.log", delete=False)
    log.close()
    proc = subprocess.Popen(
        ["Xephyr", display, "-screen", f"{width}x{height}"],
        stdout=subprocess.DEVNULL,
        stderr=open(log.name, "w"),
    )
    time.sleep(1.0)
    if proc.poll() is not None:
        err = ""
        try:
            err = Path(log.name).read_text().strip()
        except OSError:
            pass
        finally:
            try:
                os.unlink(log.name)
            except OSError:
                pass
        click.echo(f"Xephyr failed on {display}: {err or '(no output -- process died silently)'}", err=True)
        return None
    try:
        os.unlink(log.name)
    except OSError:
        pass
    return proc.pid


def minimize_xephyr(xephyr_pid: int, real_display: str) -> None:
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


# ── Hidden browser auto-launch (Zephyr + silent) ──────────────────────────

def launch_hidden_browser(
    cdp_port: int = 9222,
    user_data_dir: str | None = None,
    browser_bin: str = "google-chrome",
) -> dict | None:
    """Launch Chromium in a hidden Xephyr window with silent flags.
    
    If Xephyr is unavailable, falls back to Xvfb (fully invisible).
    
    Returns state dict on success, or None if a browser was already running.
    """
    if is_cdp_available(cdp_port):
        return None

    browser = resolve_browser(browser_bin)

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
    real_display: str | None = detect_display() or None
    mode = "xephyr"

    # ── Virtual display setup (Xephyr preferred, fallback to Xvfb) ────────
    if shutil.which("Xephyr"):
        display = find_free_display()
        xephyr_pid = start_xephyr(display)
        if xephyr_pid is not None:
            if real_display:
                minimize_xephyr(xephyr_pid, real_display)
        else:
            click.echo("Xephyr failed to start — falling back to Xvfb.", err=True)

    if xephyr_pid is None:
        if not shutil.which("Xvfb"):
            raise click.ClickException(
                "No virtual display server available. Install Xephyr or Xvfb."
            )
        if display is None:
            display = find_free_display()
        xvfb_pid = start_xvfb(display)
        mode = "xvfb"

    env.pop("WAYLAND_DISPLAY", None)
    env.pop("XDG_SESSION_TYPE", None)
    env["DISPLAY"] = display
    cmd.append("--ozone-platform=x11")

    # Silent flags (always applied for virtual display)
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

    # ── Launch ──────────────────────────────────────────────────────────────
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
            state = {
                "mode": mode,
                "cdp_port": cdp_port,
                "xvfb_pid": xvfb_pid,
                "xephyr_pid": xephyr_pid,
                "display": display,
                "real_display": real_display,
            }
            write_browser_state(state)
            return state
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

    raise click.ClickException("Failed to start hidden browser.")
