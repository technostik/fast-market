from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from core.models import Action, ItemMetadata, Source


def _get_source_url(source: Source) -> str:
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
    action: Action, item: ItemMetadata, source: Source, rule_id: str
) -> tuple[int, str, str]:
    """Execute action with placeholders replaced.

    Returns:
        tuple[int, str, str]: (exit_code, output, script_content)
    """

    placeholders = {
        "RULE_ID": rule_id,
        "SOURCE_ID": source.id,
        "SOURCE_PLUGIN": source.plugin,
        "SOURCE_ORIGIN": source.origin,
        "SOURCE_URL": _get_source_url(source),
        "SOURCE_DESC": source.description or "",
        "ITEM_ID": item.id,
        "ITEM_TITLE": item.title,
        "ITEM_URL": item.url,
        "ITEM_CONTENT_TYPE": item.content_type,
        "ITEM_PUBLISHED": item.published_at.isoformat(),
        **{f"EXTRA_{k.upper()}": str(v) for k, v in item.extra.items()},
    }

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

        result = subprocess.run([tmp_path], capture_output=True, text=True, timeout=300)
        return result.returncode, result.stdout + result.stderr, script_content
    except subprocess.TimeoutExpired as e:
        return -1, f"Timeout: {str(e)}", script_content
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
