from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import Action, ItemMetadata, Source
from common.rt_subprocess import rt_subprocess

# Login shells often put /usr/bin before pyenv shims, shadowing fast-market CLIs
# (e.g. /usr/bin/skill vs the skill-agent entry point).
_LOGIN_SHELL_PATH_PREFIX = (
    'export PATH="${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:${PATH}"'
)


def _wrap_login_shell_command(command: str) -> str:
    """Run command in a login shell with fast-market CLIs ahead of system binaries."""
    return f"{_LOGIN_SHELL_PATH_PREFIX}\n{command}"


def format_action_error_output(command: str, output: str) -> str:
    """Prefix subprocess output with the resolved command for debugging."""
    body = output if output else "(no output)"
    return f"--- Command ---\n{command}\n--- Output ---\n{body}"


def _get_source_url(source: Source, item: ItemMetadata | None = None) -> str:
    """Get the source URL, preferring channel-specific URL for channel_list sources."""
    # For channel_list sources, use channel-specific URL from item.extra if available
    if source.plugin == "channel_list" and item:
        channel_url = item.extra.get("channel_url")
        if channel_url:
            return channel_url

    identifier = source.origin

    if source.plugin == "youtube":
        if identifier.startswith("UC"):
            return f"https://www.youtube.com/channel/{identifier}"
        elif identifier.startswith("@"):
            return f"https://www.youtube.com/{identifier}"
        elif "youtube.com/channel/" in identifier:
            return identifier
        elif "youtube.com/@" in identifier:
            return identifier
        elif "youtube.com/c/" in identifier:
            return identifier
        elif "youtube.com/user/" in identifier:
            return identifier
        else:
            return f"https://www.youtube.com/channel/{identifier}"

    return identifier


def _build_placeholders(
    action: Action,
    item: ItemMetadata,
    source: Source,
    rule_id: str,
    error_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    rule_time = datetime.now(timezone.utc).isoformat()

    source_desc = source.description or ""
    if source.plugin == "channel_list" and item:
        channel_name = item.extra.get("channel_name")
        if channel_name:
            source_desc = f"{source_desc} ({channel_name})" if source_desc else channel_name

    placeholders = {
        "RULE_ID": rule_id,
        "SOURCE_ID": source.id,
        "SOURCE_PLUGIN": source.plugin,
        "SOURCE_ORIGIN": source.origin,
        "SOURCE_URL": _get_source_url(source, item),
        "SOURCE_DESC": source_desc,
        "ITEM_ID": item.id,
        "ITEM_TITLE": item.title,
        "ITEM_URL": item.url,
        "ITEM_CONTENT_TYPE": item.content_type,
        "ITEM_PUBLISHED": item.published_at.isoformat() if item.published_at else "",
        "RULE_TIME": rule_time,
        **{f"EXTRA_{k.upper()}": str(v) for k, v in item.extra.items()},
    }

    if error_context:
        rule_error = error_context.get("rule_error", "")
        rule_result = error_context.get("rule_result", "")
        rule_msg = error_context.get("rule_msg", "")

        placeholders["RULE_ERROR"] = str(rule_error) if rule_error is not None else ""
        placeholders["RULE_RESULT"] = str(rule_result) if rule_result is not None else ""
        placeholders["RULE_MSG"] = str(rule_msg) if rule_msg is not None else ""
    else:
        placeholders["RULE_ERROR"] = ""
        placeholders["RULE_RESULT"] = ""
        placeholders["RULE_MSG"] = ""

    return placeholders


def resolve_action_command(
    action: Action,
    item: ItemMetadata,
    source: Source,
    rule_id: str,
    error_context: dict[str, Any] | None = None,
) -> str:
    """Return the action command with placeholders substituted."""
    command = action.command
    for key, value in _build_placeholders(
        action, item, source, rule_id, error_context
    ).items():
        command = command.replace(f"${{{key}}}", value)
        command = command.replace(f"${key}", value)
    return command


def execute_action(
    action: Action,
    item: ItemMetadata,
    source: Source,
    rule_id: str,
    error_context: dict[str, Any] | None = None,
    workdir: Path | None = None,
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """Execute action with placeholders replaced.

    Args:
        action: The action to execute
        item: The matched item that triggered the rule
        source: The source that provided the item
        rule_id: The ID of the rule that matched
        error_context: Optional dict with error/execution context for on_error/on_execution actions.
            Can contain: rule_error, rule_result, rule_time, rule_msg

    Returns:
        tuple[int, str, str]: (exit_code, output, script_content)
    """

    command = resolve_action_command(action, item, source, rule_id, error_context)
    script_content = f"#!/bin/bash\n{command}"

    if action.precondition:
        pre = rt_subprocess.run(
            ["bash", "-l", "-c", _wrap_login_shell_command(action.precondition)],
            capture_output=True,
            text=True,
            cwd=workdir,
            env=os.environ.copy(),
        )
        pre_output = (pre.stdout or "") + (pre.stderr or "")
        if pre.returncode != 0:
            return (
                pre.returncode,
                format_action_error_output(action.precondition, f"[precondition failed]\n{pre_output}"),
                f"#!/bin/bash\n{action.precondition}",
            )

    # Use login shell so ~/.profile is sourced (nvm, pyenv, etc.) regardless of caller env
    result = rt_subprocess.run(
        ["bash", "-l", "-c", _wrap_login_shell_command(command)],
        capture_output=True,
        text=True,
        cwd=workdir,
        env=os.environ.copy(),
        timeout=timeout,
    )
    raw_output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        return result.returncode, format_action_error_output(command, raw_output), script_content
    return result.returncode, raw_output, script_content
