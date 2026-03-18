from __future__ import annotations

from common.core.config import load_tool_config


def load_config() -> dict:
    return load_tool_config("youtube")
