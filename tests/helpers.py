"""Test helper functions for session analysis."""

from __future__ import annotations

from pathlib import Path

import yaml


def count_session_errors(session_file: Path) -> int:
    """Count tool call errors in a saved session yaml."""
    if not session_file.exists():
        return 0
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}
    metrics = data.get("metrics", {})
    if "error_count" in metrics:
        return int(metrics["error_count"])

    count = 0
    for turn in data.get("turns", []):
        for tc in turn.get("tool_calls", []):
            exit_code = tc.get("exit_code")
            if exit_code is not None and exit_code != 0:
                count += 1
    return count


def count_session_guesses(session_file: Path) -> int:
    """Count guess attempts in a saved session yaml."""
    if not session_file.exists():
        return 0
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}
    metrics = data.get("metrics", {})
    return int(metrics.get("guess_count", 0))


def count_total_steps(session_file: Path) -> int:
    """Count total number of skill executions (tool calls) in a session."""
    if not session_file.exists():
        return 0
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}
    metrics = data.get("metrics", {})
    if "total_tool_calls" in metrics:
        return int(metrics["total_tool_calls"])

    count = 0
    for turn in data.get("turns", []):
        count += len(turn.get("tool_calls", []))
    return count


def count_total_rounds(session_file: Path) -> int:
    """Count total number of rounds (assistant turns) in a session."""
    if not session_file.exists():
        return 0
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}
    metrics = data.get("metrics", {})
    if "iterations_used" in metrics:
        return int(metrics["iterations_used"])

    count = 0
    for turn in data.get("turns", []):
        if turn.get("role") == "assistant":
            count += 1
    return count


def count_exploratory_commands(session_file: Path) -> int:
    """Count exploratory commands (--help, -h, etc.) that indicate learning/guessing."""
    if not session_file.exists():
        return 0
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}

    count = 0
    for turn in data.get("turns", []):
        for tc in turn.get("tool_calls", []):
            arguments = tc.get("arguments", {})
            command = arguments.get("command", "")
            if "--help" in command or " -h " in command or command.endswith(" -h"):
                count += 1
    return count


def get_session_metrics(session_file: Path) -> dict:
    """Return full metrics dict from a session file."""
    if not session_file.exists():
        return {}
    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}
    return data.get("metrics", {})
