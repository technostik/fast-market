from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import click

from common.cli.helpers import out as _out

_AGENT_BROWSER = "agent-browser"

_TOOL_ROOT = Path(__file__).resolve().parents[1]


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
    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])
    return cmd


def run_agent_cmd(
    instruction: str,
    cdp_port: int = 9222,
    timeout: int | None = None,
    capture_stderr: bool = True,
) -> subprocess.CompletedProcess:
    """Run an agent-browser instruction and return the result."""
    cmd = build_agent_cmd(instruction, cdp_port, timeout)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )


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
