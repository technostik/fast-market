from __future__ import annotations

from pathlib import Path

from common import structlog
from common.core.config import load_tool_config
from common.core.registry import build_plugins

logger = structlog.get_logger(__name__)
_TOOL_ROOT = Path(__file__).resolve().parents[1]


def build_engine(verbose: bool) -> dict:
    """Build configured LLM provider instances."""
    config = load_tool_config("prompt")
    providers = build_plugins(config, tool_root=_TOOL_ROOT)
    return providers


def get_default_provider(config: dict | None = None) -> str:
    """Get the configured default LLM provider."""
    if config is None:
        config = load_tool_config("prompt")
    default_provider = config.get("default_provider", "")
    if not isinstance(default_provider, str):
        raise ValueError("default_provider must be a string")
    return default_provider or "anthropic"
