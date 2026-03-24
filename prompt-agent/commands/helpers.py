from __future__ import annotations

from common import structlog
from common.core.config import load_tool_config
from common.llm.registry import discover_providers, get_default_provider_name

logger = structlog.get_logger(__name__)


def build_engine(verbose: bool) -> dict:
    """Build configured LLM provider instances for prompt tool."""
    config = load_tool_config("prompt")
    return discover_providers(config)


def get_default_provider(config: dict | None = None) -> str:
    """Get the configured default LLM provider name."""
    if config is None:
        config = load_tool_config("prompt")
    return get_default_provider_name(config)
