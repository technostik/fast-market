from __future__ import annotations

from common.core.config import load_tool_config

__all__ = ["load_config"]

_TOOL_NAME = "browser"


def load_config() -> dict[str, object]:
    return load_tool_config(_TOOL_NAME)
