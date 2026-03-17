from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.models import Document


@dataclass(slots=True)
class ItemMeta:
    source_id: str
    updated_at: datetime | None = None
    metadata: dict[str, object] | None = None


class SourcePlugin(ABC):
    name: str

    @abstractmethod
    def list_items(
        self,
        limit: int,
        known_id_dates: dict[str, datetime | None] | None = None,
    ) -> list[ItemMeta]:
        """Return up to `limit` items that need indexing (new or modified).

        Args:
            limit:          Maximum number of items to return.
            known_id_dates: {source_id: indexed_updated_at} for all already-indexed
                            documents of this source. Empty dict on backfill.
                            Plugins use this to decide what to skip:
                            - YouTube: skip if source_id is a key (ID-based dedup).
                            - Obsidian: skip if source_id is a key AND mtime has not
                              advanced past indexed_updated_at (re-index on change).
        """
        raise NotImplementedError

    @abstractmethod
    def fetch(self, item_meta: ItemMeta) -> Document:
        raise NotImplementedError


@dataclass
class PluginManifest:
    """
    Everything a plugin contributes beyond its SourcePlugin logic.

    Fields:
        name:                 Must match SourcePlugin.name.
        source_plugin_class:  The SourcePlugin subclass (not an instance).
        cli_options:          {command_name: [click.Option, ...]}
                              Keys are CLI command names ("search", "sync", …).
                              Use "*" to inject into ALL commands.
        api_router:           Optional FastAPI APIRouter with plugin-specific endpoints.
        frontend_js:          Optional JS snippet injected into frontend pages.
    """

    name: str
    source_plugin_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
    frontend_js: str | None = None
