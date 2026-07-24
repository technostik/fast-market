from __future__ import annotations

from pathlib import Path

from common import structlog
from common.cli.helpers import out
from common.core.config import load_tool_config
from common.llm.registry import discover_providers, get_default_provider_name
from storage.store import RagStore, create_engine_for_rag, make_session_factory

logger = structlog.get_logger(__name__)


def get_rag_store(db_path: str | None = None) -> tuple[RagStore, object]:
    engine = create_engine_for_rag(db_path)
    sf = make_session_factory(engine)
    store = RagStore(sf)
    store.ensure_tables(engine)
    return store, engine


def resolve_provider_and_model(
    provider_name: str | None = None, model_name: str | None = None
):
    config = load_tool_config("rag")
    providers = discover_providers(config)
    if provider_name:
        if provider_name not in providers:
            raise SystemExit(
                f"Provider {provider_name!r} not found. Available: {list(providers.keys())}"
            )
        llm = providers[provider_name]
    else:
        default_name = get_default_provider_name(config)
        llm = providers[default_name]
    return llm, model_name


__all__ = ["out", "get_rag_store", "resolve_provider_and_model"]
