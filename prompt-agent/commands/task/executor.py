from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from common import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    original_command: str | None = None
    resolved_from_alias: str | None = None

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "original_command": self.original_command,
            "resolved_from_alias": self.resolved_from_alias,
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
    if cmd_str.startswith("skill:"):
        from common.core.paths import get_skills_dir

        skill_ref = cmd_str[6:]
        skill_path_part, _, args_part = skill_ref.partition(" ")
        if not skill_path_part or "/" not in skill_path_part:
            return {
                "command": cmd_str,
                "resolved_command": cmd_str,
                "alias_used": None,
                "allowed": False,
                "would_execute": False,
                "reason": "Invalid skill format. Use: skill:name/script [args]",
            }
        skill_name, script_name = skill_path_part.split("/", 1)
        script_path = get_skills_dir() / skill_name / "scripts" / script_name
        if not script_path.exists():
            return {
                "command": cmd_str,
                "resolved_command": cmd_str,
                "alias_used": None,
                "allowed": False,
                "would_execute": False,
                "reason": f"Skill script not found: {skill_name}/{script_name}",
            }
        return {
            "command": cmd_str,
            "resolved_command": f"{script_path} {args_part}".strip(),
            "alias_used": None,
            "allowed": True,
            "would_execute": True,
            "workdir": str(workdir),
        }

    resolved_cmd, alias_used = _resolve_alias(cmd_str)

    if not is_command_allowed(resolved_cmd, allowed):
        return {
            "command": cmd_str,
            "resolved_command": resolved_cmd,
            "alias_used": alias_used,
            "allowed": False,
            "would_execute": False,
            "reason": f"Command not allowed: {shlex.split(resolved_cmd)[0]}",
        }
    if reject_absolute_paths(resolved_cmd):
        return {
            "command": cmd_str,
            "resolved_command": resolved_cmd,
            "alias_used": alias_used,
            "allowed": True,
            "would_execute": False,
            "reason": "Absolute paths not allowed",
        }
    return {
        "command": cmd_str,
        "resolved_command": resolved_cmd,
        "alias_used": alias_used,
        "allowed": True,
        "would_execute": True,
        "workdir": str(workdir),
    }


def _resolve_alias(cmd_str: str) -> tuple[str, str | None]:
    """Resolve an alias in the command string.

    Returns (resolved_command, alias_name_or_none).
    """
    try:
        from common.core.aliases import resolve_alias

        return resolve_alias(cmd_str)
    except Exception:
        return cmd_str, None


def execute_skill_command(
    skill_ref: str,
    workdir: Path,
    timeout: int,
) -> CommandResult:
    """Execute a skill script.

    Format: skill_name/script_name [args]
    """
    from common.core.paths import get_skills_dir

    skill_path_part, _, args_part = skill_ref.partition(" ")
    if not skill_path_part or "/" not in skill_path_part:
        return CommandResult(
            command=f"skill:{skill_ref}",
            stdout="",
            stderr="Invalid skill format. Use: skill:name/script [args]",
            exit_code=1,
        )

    skill_name, script_name = skill_path_part.split("/", 1)
    script_path = get_skills_dir() / skill_name / "scripts" / script_name

    if not script_path.exists():
        return CommandResult(
            command=f"skill:{skill_ref}",
            stdout="",
            stderr=f"Skill script not found: {skill_name}/{script_name}",
            exit_code=1,
        )

    if not script_path.is_file():
        return CommandResult(
            command=f"skill:{skill_ref}",
            stdout="",
            stderr=f"Not a file: {skill_name}/{script_name}",
            exit_code=1,
        )

    try:
        cmd_parts = [str(script_path)]
        if args_part:
            cmd_parts.extend(shlex.split(args_part))
        result = subprocess.run(
            cmd_parts,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            command=f"skill:{skill_ref}",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            command=f"skill:{skill_ref}",
            stdout="",
            stderr=f"Skill script timed out after {timeout} seconds",
            exit_code=124,
            timed_out=True,
        )
    except Exception as exc:
        return CommandResult(
            command=f"skill:{skill_ref}",
            stdout="",
            stderr=str(exc),
            exit_code=1,
        )


def resolve_and_execute_command(
    cmd_str: str,
    workdir: Path,
    allowed: set[str],
    timeout: int = 60,
) -> CommandResult:
    """Execute a command with alias resolution and skill script support.

    Resolves any aliases in the command before execution.
    Supports skill: prefix for executing skill scripts.
    Tracks original command and alias for debugging.
    """
    if cmd_str.startswith("skill:"):
        return execute_skill_command(cmd_str[6:], workdir, timeout)

    resolved_cmd, alias_used = _resolve_alias(cmd_str)

    if resolved_cmd != cmd_str:
        logger.debug(
            "alias resolved",
            original=cmd_str,
            resolved=resolved_cmd,
            alias=alias_used,
        )

    result = _execute_whitelisted_command(resolved_cmd, workdir, allowed, timeout)

    if result.exit_code != 0 and alias_used:
        result.stderr = f"{result.stderr}\n(from alias '{alias_used}')".strip()

    result.original_command = cmd_str if cmd_str != resolved_cmd else None
    result.resolved_from_alias = alias_used

    return result


def _execute_whitelisted_command(
    cmd_str: str,
    workdir: Path,
    allowed: set[str],
    timeout: int,
) -> CommandResult:
    """Execute a whitelisted command (internal)."""
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
