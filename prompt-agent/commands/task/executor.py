from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
        }


_DEFAULT_ALLOWED = {
    "corpus",
    "image",
    "youtube",
    "message",
    "prompt",
    "ls",
    "cat",
    "jq",
    "grep",
    "find",
    "echo",
    "head",
    "tail",
    "wc",
    "mkdir",
    "touch",
    "rm",
    "cp",
    "mv",
    "sort",
    "uniq",
    "awk",
    "sed",
}


def is_command_allowed(cmd_str: str, allowed: set[str]) -> bool:
    """Check if command is in whitelist (first token must match basename)."""
    try:
        tokens = shlex.split(cmd_str)
    except ValueError:
        return False
    if not tokens:
        return False
    first_token = tokens[0]
    cmd_name = Path(first_token).name
    return cmd_name in allowed


def validate_workdir(workdir: Path, forbidden: list[Path]) -> None:
    """Ensure workdir is not a sensitive location."""
    workdir = workdir.resolve()
    for f in forbidden:
        if f == Path("/"):
            continue
        try:
            f_resolved = f.resolve()
        except Exception:
            continue
        if workdir == f_resolved:
            raise ValueError(f"Workdir cannot be {f}")
        if str(workdir).startswith(str(f_resolved)) and f_resolved != workdir:
            raise ValueError(f"Workdir cannot be in {f}")


def reject_absolute_paths(cmd_str: str) -> bool:
    """Reject commands with absolute paths in arguments."""
    try:
        tokens = shlex.split(cmd_str)
    except ValueError:
        return True
    for token in tokens[1:]:
        if token.startswith("/") and len(token) > 1:
            return True
    return False


def execute_command(
    cmd_str: str,
    workdir: Path,
    allowed: set[str],
    timeout: int = 60,
) -> CommandResult:
    """Execute a whitelisted command in the workdir."""
    if not is_command_allowed(cmd_str, allowed):
        return CommandResult(
            command=cmd_str,
            stdout="",
            stderr=f"Command not allowed: {shlex.split(cmd_str)[0]}",
            exit_code=126,
        )

    if reject_absolute_paths(cmd_str):
        return CommandResult(
            command=cmd_str,
            stdout="",
            stderr="Absolute paths not allowed in command arguments",
            exit_code=126,
        )

    try:
        result = subprocess.run(
            shlex.split(cmd_str),
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            command=cmd_str,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            command=cmd_str,
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
            exit_code=124,
            timed_out=True,
        )
    except Exception as exc:
        return CommandResult(
            command=cmd_str,
            stdout="",
            stderr=str(exc),
            exit_code=1,
        )


def execute_dry_run(cmd_str: str, workdir: Path, allowed: set[str]) -> dict:
    """Simulate execution for dry-run mode."""
    if not is_command_allowed(cmd_str, allowed):
        return {
            "command": cmd_str,
            "allowed": False,
            "would_execute": False,
            "reason": f"Command not allowed: {shlex.split(cmd_str)[0]}",
        }
    if reject_absolute_paths(cmd_str):
        return {
            "command": cmd_str,
            "allowed": True,
            "would_execute": False,
            "reason": "Absolute paths not allowed",
        }
    return {
        "command": cmd_str,
        "allowed": True,
        "would_execute": True,
        "workdir": str(workdir),
    }
