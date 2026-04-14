from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import Action, ItemMetadata, Source
from common.rt_subprocess import rt_subprocess


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


def execute_action(
    action: Action,
    item: ItemMetadata,
    source: Source,
    rule_id: str,
    error_context: dict[str, Any] | None = None,
    workdir: Path | None = None,
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

    rule_time = datetime.now(timezone.utc).isoformat()

    # For channel_list sources, use channel-specific description from item.extra
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
        "ITEM_PUBLISHED": item.published_at.isoformat(),
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

    command = action.command
    for key, value in placeholders.items():
        command = command.replace(f"${{{key}}}", value)
        command = command.replace(f"${key}", value)

    script_content = f"#!/bin/bash\n{command}"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/bash\n")
            f.write(command)
            f.flush()
            tmp_path = f.name

        os.chmod(tmp_path, 0o755)

        result = rt_subprocess.run([tmp_path], capture_output=True, text=True, cwd=workdir)
        return result.returncode, (result.stdout or "") + (result.stderr or ""), script_content
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
