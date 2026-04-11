"""Browse tool definition and execution for the browser run command.

The LLM gets a single tool called ``browse`` that accepts an action and
arguments.  Internally this builds and runs an ``agent-browser`` subprocess.
Placeholder substitution (``{key}``) is applied so users can pass file
paths and other values via ``-p KEY=VALUE``.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Tool definition (OpenAI-style function calling)
# ---------------------------------------------------------------------------

# All first-word sub-commands that agent-browser supports.
# These are listed in the enum so the LLM knows what is valid.
_BROWSER_ACTIONS = [
    "open", "click", "dblclick", "fill", "type", "press", "keyboard",
    "keydown", "keyup", "hover", "select", "check", "uncheck", "scroll",
    "scrollintoview", "drag", "upload", "screenshot", "snapshot", "pdf",
    "eval", "connect", "close", "chat",
    "get", "is", "find", "wait", "batch",
    "clipboard", "mouse",
    "set", "cookies", "storage",
    "network",
    "tab", "window", "frame", "dialog",
    "diff",
    "trace", "profiler", "console", "errors", "highlight", "inspect",
    "state",
    "back", "forward", "reload",
    "stream",
]


def build_browse_tool() -> dict:
    """Return the OpenAI-style function tool definition for ``browse``."""
    actions_str = ", ".join(_BROWSER_ACTIONS)
    return {
        "type": "function",
        "function": {
            "name": "browse",
            "description": (
                "Interact with a web browser.  Use this tool for ALL browser "
                "operations: navigation, clicking, filling forms, taking screenshots, "
                "extracting content, managing cookies, etc.\n"
                f"Available actions: {actions_str}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "The browser action to perform. "
                            f"One of: {actions_str}"
                        ),
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Arguments for the action.  You can use {key} placeholders "
                            "that will be replaced by task parameters passed with -p."
                        ),
                    },
                    "explanation": {
                        "type": "string",
                        "description": (
                            "Brief explanation of why you are performing this action."
                        ),
                    },
                },
                "required": ["action"],
            },
        },
    }


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

@dataclass
class BrowseResult:
    """Result of executing a browse action."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    action: str = ""
    command_line: str = ""
    warning: str = ""


# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------

def substitute_params(
    args: list[str],
    params: dict[str, str],
) -> list[str]:
    """Replace ``{key}`` placeholders in each argument."""
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            return match.group(0)  # leave unknown placeholders as-is
        return params[key]

    return [re.sub(r"\{(\w+)\}", _replace, a) for a in args]


# ---------------------------------------------------------------------------
# Command building & execution
# ---------------------------------------------------------------------------

_AGENT_BROWSER = "agent-browser"


def _build_agent_cmd(
    action: str,
    args: list[str],
    cdp_port: int,
    timeout: int | None,
) -> list[str]:
    """Build the ``agent-browser`` command line."""
    cmd = [_AGENT_BROWSER, "--cdp", str(cdp_port), action, *args]
    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])
    return cmd


def execute_browse_action(
    action: str,
    args: list[str],
    *,
    cdp_port: int = 9222,
    timeout: int | None = None,
    params: dict[str, str] | None = None,
) -> BrowseResult:
    """Execute a single browse action via ``agent-browser``.

    Placeholders in *args* like ``{video_file}`` are resolved from *params*.
    """
    resolved_args = substitute_params(args, params or {})

    # Build the command-line string for display purposes
    cmd_for_display = shlex.join([_AGENT_BROWSER, action, *resolved_args])

    cmd = _build_agent_cmd(action, resolved_args, cdp_port, timeout)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout / 1000 if timeout else None,
        )
        return BrowseResult(
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            exit_code=result.returncode,
            action=action,
            command_line=cmd_for_display,
        )
    except subprocess.TimeoutExpired:
        return BrowseResult(
            stdout="",
            stderr=f"Command timed out after {timeout}ms",
            exit_code=1,
            timed_out=True,
            action=action,
            command_line=cmd_for_display,
        )
    except FileNotFoundError:
        return BrowseResult(
            stdout="",
            stderr=(
                f"'{_AGENT_BROWSER}' not found on PATH. "
                f"Install with: npm install -g {_AGENT_BROWSER}"
            ),
            exit_code=127,
            action=action,
            command_line=cmd_for_display,
        )
    except Exception as exc:
        return BrowseResult(
            stdout="",
            stderr=str(exc),
            exit_code=1,
            action=action,
            command_line=cmd_for_display,
        )


def format_browse_result(result: BrowseResult, max_output: int = 5000) -> str:
    """Format a BrowseResult for the LLM tool response."""
    stdout = result.stdout
    if len(stdout) > max_output:
        stdout = stdout[:max_output] + "\n... [truncated]"

    stderr = result.stderr
    if len(stderr) > 2000:
        stderr = stderr[:2000] + "\n... [truncated]"

    lines = [
        f"Action: {result.command_line}",
        f"Exit code: {result.exit_code}",
        f"Stdout:",
        stdout if stdout else "(empty)",
        f"Stderr:",
        stderr if stderr else "(empty)",
        f"Timed out: {result.timed_out}",
    ]
    if result.warning:
        lines.append(f"Warning: {result.warning}")
    return "\n".join(lines)
