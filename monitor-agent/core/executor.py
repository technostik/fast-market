from __future__ import annotations

import os
import subprocess
import tempfile

from core.models import Action, ItemMetadata, Source


def execute_action(
    action: Action, item: ItemMetadata, source: Source, rule_name: str
) -> tuple[int, str]:
    """Execute action with placeholders replaced."""

    placeholders = {
        "THEMATIC": rule_name,
        "RULE_NAME": rule_name,
        "SOURCE_ID": source.id,
        "SOURCE_PLUGIN": source.plugin,
        "SOURCE_URL": source.identifier,
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

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/bash\n")
            f.write(command)
            f.flush()
            tmp_path = f.name

        os.chmod(tmp_path, 0o755)

        result = subprocess.run([tmp_path], capture_output=True, text=True, timeout=300)
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as e:
        return -1, f"Timeout: {str(e)}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
